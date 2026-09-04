"""AGENT 1 — Context & RAG Ingest.

Responsibilities
  1. Parse + chunk the source document.
  2. Index it into the hybrid vector store.
  3. Extract concepts and build a prerequisite DAG (LLM-guided, statistically
     grounded, cycle-safe) and emit a topological teaching order.

The DAG construction never trusts the LLM blindly: proposed edges are validated
against the graph and any edge that would create a cycle is dropped, so the
downstream planner always receives a valid DAG.
"""
from __future__ import annotations

import math
import re
import uuid
from collections import Counter, defaultdict

from app.core.llm import llm
from app.core.schemas import Chunk, Concept, KnowledgeGraph
from app.ingest.parser import chunk_document
from app.ingest.vector_store import store, tokenize

SYSTEM = (
    "You are a curriculum architect. Given document excerpts, extract the minimal set of "
    "teachable concepts and their prerequisite relations. Prefer 5-12 concepts. "
    "Difficulty is 0..1. est_minutes is realistic lecture time."
)


# --------------------------------------------------------------------------- #
# Statistical concept mining (works with zero API keys)
# --------------------------------------------------------------------------- #
def _tfidf_keyphrases(chunks: list[Chunk], top_n: int = 14) -> list[tuple[str, list[str]]]:
    df: Counter = Counter()
    per_chunk: list[Counter] = []
    for ch in chunks:
        toks = tokenize(ch.text)
        grams = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]
        c = Counter(grams)
        per_chunk.append(c)
        for g in c:
            df[g] += 1
    N = max(len(chunks), 1)
    scores: dict[str, float] = defaultdict(float)
    owners: dict[str, list[str]] = defaultdict(list)
    for ch, c in zip(chunks, per_chunk):
        for g, f in c.items():
            if df[g] < 2 or len(g) < 4:
                continue
            s = (1 + math.log(f)) * math.log(N / df[g] + 1)
            if " " in g:
                s *= 1.6  # bigrams are usually the real concept names
            scores[g] += s
            owners[g].append(ch.id)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    picked: list[tuple[str, list[str]]] = []
    for g, _ in ranked:
        if any(g in p or p in g for p, _ in picked):
            continue
        picked.append((g, owners[g][:4]))
        if len(picked) >= top_n:
            break
    return picked


def _heuristic_concepts(chunks: list[Chunk]) -> list[Concept]:
    # Prefer document sections when the parser found real headings.
    sections: dict[str, list[Chunk]] = defaultdict(list)
    for ch in chunks:
        if ch.section:
            sections[ch.section].append(ch)
    concepts: list[Concept] = []
    if len(sections) >= 3:
        for i, (name, chs) in enumerate(list(sections.items())[:12]):
            body = " ".join(c.text for c in chs)
            concepts.append(
                Concept(
                    id=f"c{i}",
                    name=name[:80],
                    summary=body[:300],
                    difficulty=min(0.95, 0.25 + 0.06 * i),
                    est_minutes=round(min(12.0, 3 + len(body) / 1400), 1),
                    chunk_ids=[c.id for c in chs][:6],
                    keywords=[k for k, _ in Counter(tokenize(body)).most_common(6)],
                )
            )
    else:
        for i, (phrase, ids) in enumerate(_tfidf_keyphrases(chunks, 10)):
            body = " ".join(c.text for c in store.by_ids(ids))
            concepts.append(
                Concept(
                    id=f"c{i}",
                    name=phrase.title(),
                    summary=body[:300],
                    difficulty=min(0.95, 0.25 + 0.07 * i),
                    est_minutes=round(min(12.0, 3 + len(body) / 1400), 1),
                    chunk_ids=ids,
                    keywords=phrase.split(),
                )
            )
    # Linear prerequisite chain as the statistical prior: earlier -> later.
    for prev, cur in zip(concepts, concepts[1:]):
        cur.prerequisites = [prev.id]
    return concepts


# --------------------------------------------------------------------------- #
# DAG utilities
# --------------------------------------------------------------------------- #
def _creates_cycle(edges: dict[str, set[str]], src: str, dst: str) -> bool:
    """True if adding prerequisite src->dst introduces a cycle."""
    stack, seen = [src], set()
    while stack:
        n = stack.pop()
        if n == dst:
            return True
        if n in seen:
            continue
        seen.add(n)
        stack.extend(edges.get(n, ()))
    return False


def topological_order(concepts: list[Concept]) -> list[str]:
    """Kahn's algorithm, tie-broken by (difficulty, original index) for stable,
    pedagogically sensible ordering."""
    index = {c.id: i for i, c in enumerate(concepts)}
    indeg = {c.id: 0 for c in concepts}
    adj: dict[str, list[str]] = defaultdict(list)
    for c in concepts:
        for p in c.prerequisites:
            if p in indeg:
                adj[p].append(c.id)
                indeg[c.id] += 1
    ready = sorted([i for i, d in indeg.items() if d == 0], key=lambda i: index[i])
    order: list[str] = []
    by_id = {c.id: c for c in concepts}
    while ready:
        ready.sort(key=lambda i: (by_id[i].difficulty, index[i]))
        n = ready.pop(0)
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
    # Any remaining nodes were in a cycle — append deterministically.
    order += [c.id for c in concepts if c.id not in order]
    return order


# --------------------------------------------------------------------------- #
class ContextAgent:
    async def ingest(self, filename: str, data: bytes) -> tuple[str, KnowledgeGraph]:
        doc_id = uuid.uuid4().hex[:12]
        chunks = chunk_document(doc_id, filename, data)
        if not chunks:
            raise ValueError("No extractable text found in document.")
        store.add(chunks)
        concepts = await self._extract_concepts(chunks)
        self._validate_dag(concepts)
        kg = KnowledgeGraph(doc_id=doc_id, concepts=concepts, order=topological_order(concepts))
        return doc_id, kg

    async def _extract_concepts(self, chunks: list[Chunk]) -> list[Concept]:
        baseline = _heuristic_concepts(chunks)
        # Sample representative excerpts to keep the prompt cheap and on-topic.
        step = max(1, len(chunks) // 12)
        excerpt = "\n---\n".join(
            f"[{c.id}] p{c.page} {c.section}: {c.text[:420]}" for c in chunks[::step][:12]
        )
        spec = (
            '{"concepts":[{"id":"c0","name":"","summary":"","difficulty":0.4,'
            '"est_minutes":6,"prerequisites":["c..."],"chunk_ids":["<ids from excerpts>"],'
            '"keywords":[""]}]}'
        )
        data = await llm.json_call(
            SYSTEM, f"Schema: {spec}\n\nExcerpts:\n{excerpt}", fallback=None
        )
        if not isinstance(data, dict) or not data.get("concepts"):
            return baseline
        valid_chunk_ids = {c.id for c in chunks}
        out: list[Concept] = []
        for i, raw in enumerate(data["concepts"][:14]):
            try:
                cid = str(raw.get("id") or f"c{i}")
                out.append(
                    Concept(
                        id=cid,
                        name=str(raw.get("name", f"Concept {i+1}"))[:90],
                        summary=str(raw.get("summary", ""))[:500],
                        difficulty=float(raw.get("difficulty", 0.5)),
                        est_minutes=float(raw.get("est_minutes", 6)),
                        prerequisites=[str(p) for p in raw.get("prerequisites", [])],
                        chunk_ids=[c for c in raw.get("chunk_ids", []) if c in valid_chunk_ids],
                        keywords=[str(k) for k in raw.get("keywords", [])][:8],
                    )
                )
            except Exception:
                continue
        if len(out) < 3:
            return baseline
        # Backfill retrieval anchors for concepts the LLM did not cite.
        for c in out:
            if not c.chunk_ids:
                hits = store.search(f"{c.name} {' '.join(c.keywords)}", k=3)
                c.chunk_ids = [h.id for h, _ in hits]
        return out

    @staticmethod
    def _validate_dag(concepts: list[Concept]) -> None:
        ids = {c.id for c in concepts}
        edges: dict[str, set[str]] = defaultdict(set)
        for c in concepts:
            kept: list[str] = []
            for p in dict.fromkeys(c.prerequisites):
                if p == c.id or p not in ids:
                    continue
                if _creates_cycle(edges, c.id, p):
                    continue  # would close a loop -> drop
                edges[p].add(c.id)
                kept.append(p)
            c.prerequisites = kept


context_agent = ContextAgent()

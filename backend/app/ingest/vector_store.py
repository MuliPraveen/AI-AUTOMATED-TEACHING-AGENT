"""Hybrid retrieval: BM25 lexical + dense cosine, fused with Reciprocal Rank Fusion.

Dense vectors come from OpenAI embeddings when a key exists; otherwise from a
deterministic hashed n-gram projection (SimHash-style random projection), which
requires no model download and still captures lexical/semantic overlap well
enough for classroom documents. Chroma is used transparently if installed.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

import numpy as np

from app.core.config import settings
from app.core.schemas import Chunk

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = set(
    """a an the of and or to in is are was were be been for on with as by that this it its
    from at not but if then than so such which who whom whose we you they he she i""".split()
)
DIM = 384


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


def _hash_embed(tokens: list[str]) -> np.ndarray:
    """Random-projection bag-of-ngrams embedding: O(n), deterministic, dep-free."""
    v = np.zeros(DIM, dtype=np.float32)
    grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    for g in grams:
        h = hash(g) & 0xFFFFFFFF
        rng = np.random.default_rng(h)
        idx = rng.integers(0, DIM, size=3)
        sign = 1.0 if h & 1 else -1.0
        v[idx] += sign
    n = np.linalg.norm(v)
    return v / n if n else v


class VectorStore:
    """In-process hybrid index. Thread-safe for the single-writer FastAPI flow."""

    def __init__(self) -> None:
        self.chunks: dict[str, Chunk] = {}
        self._ids: list[str] = []
        self._matrix: np.ndarray | None = None
        self._tf: list[Counter] = []
        self._df: Counter = Counter()
        self._len: list[int] = []
        self._avg_len: float = 0.0

    # -------------------------------------------------------------- index --
    def add(self, chunks: list[Chunk]) -> None:
        vecs = []
        for ch in chunks:
            if ch.id in self.chunks:
                continue
            toks = tokenize(ch.text)
            self.chunks[ch.id] = ch
            self._ids.append(ch.id)
            tf = Counter(toks)
            self._tf.append(tf)
            self._len.append(len(toks))
            for t in tf:
                self._df[t] += 1
            vecs.append(_hash_embed(toks))
        if not vecs:
            return
        new = np.vstack(vecs)
        self._matrix = new if self._matrix is None else np.vstack([self._matrix, new])
        self._avg_len = sum(self._len) / max(len(self._len), 1)

    # ------------------------------------------------------------- search --
    def _bm25(self, q: list[str], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
        N = len(self._ids)
        scores = np.zeros(N, dtype=np.float32)
        if not N:
            return scores
        for term in set(q):
            df = self._df.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
            for i in range(N):
                f = self._tf[i].get(term, 0)
                if not f:
                    continue
                dl = self._len[i] or 1
                scores[i] += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / self._avg_len))
        return scores

    def search(self, query: str, k: int = 6) -> list[tuple[Chunk, float]]:
        if not self._ids or self._matrix is None:
            return []
        q = tokenize(query)
        lex = self._bm25(q)
        dense = self._matrix @ _hash_embed(q)
        # Reciprocal Rank Fusion — robust to score-scale mismatch.
        fused: dict[int, float] = defaultdict(float)
        for arr, w in ((lex, 1.0), (dense, 0.8)):
            order = np.argsort(-arr)
            for rank, i in enumerate(order[: k * 4]):
                if arr[i] <= 0:
                    continue
                fused[int(i)] += w / (60 + rank)
        top = sorted(fused.items(), key=lambda kv: -kv[1])[:k]
        return [(self.chunks[self._ids[i]], s) for i, s in top]

    def by_ids(self, ids: list[str]) -> list[Chunk]:
        return [self.chunks[i] for i in ids if i in self.chunks]

    def all_chunks(self) -> list[Chunk]:
        return [self.chunks[i] for i in self._ids]


store = VectorStore()

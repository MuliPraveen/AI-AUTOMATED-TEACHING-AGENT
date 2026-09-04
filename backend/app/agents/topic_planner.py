"""§4 Topic-Based Learning + §15 AI-Generated Learning Path.

When there is no uploaded document, Agent 1's RAG corpus is replaced by a
*synthesized* syllabus: the LLM proposes a concept DAG for the requested topic
at the learner's level, and each concept carries its own generated study notes
which become the grounding context for Agent 2. Everything downstream
(planner, teaching, assessment, mastery) is unchanged — the two entry points
converge on the same KnowledgeGraph contract.
"""
from __future__ import annotations

import re

from app.agents.agent1_context import ContextAgent, topological_order
from app.core.llm import llm
from app.core.schemas import Chunk, Concept, KnowledgeGraph, LearnerProfile, Subject
from app.ingest.vector_store import store

SYSTEM = (
    "You are a curriculum designer. Produce a syllabus for the requested topic, "
    "pitched precisely at the learner's level. Order concepts so prerequisites "
    "always come first. Each concept needs substantive study notes (120-200 words) "
    "that a teacher could lecture from — real facts, definitions and examples."
)

# Keyword -> subject, for visual-grammar selection when no LLM is available.
_SUBJECT_HINTS: dict[Subject, tuple[str, ...]] = {
    Subject.MATH: ("algebra", "calculus", "matrix", "theorem", "integral", "geometry",
                   "probability", "equation", "trigonometry", "statistics"),
    Subject.PHYSICS: ("newton", "force", "quantum", "thermodynamic", "circuit", "voltage",
                      "optics", "motion", "energy", "relativity", "electricity", "current",
                      "resistance", "ohm", "ampere", "magnetic", "wave", "velocity",
                      "acceleration", "momentum", "friction", "gravity"),
    Subject.CHEMISTRY: ("molecule", "reaction", "atom", "bond", "acid", "organic",
                        "periodic", "compound", "titration"),
    Subject.BIOLOGY: ("cell", "dna", "photosynthesis", "enzyme", "genetics", "organism",
                      "protein", "evolution", "anatomy", "neuron"),
    Subject.HISTORY: ("empire", "war", "revolution", "dynasty", "century", "treaty",
                      "civilization", "colonial", "independence"),
    Subject.PROGRAMMING: ("python", "javascript", "react", "algorithm", "function", "api",
                          "database", "code", "programming", "software", "recursion",
                          "machine learning", "neural", "data structure"),
    Subject.ECONOMICS: ("market", "demand", "supply", "inflation", "gdp", "trade",
                        "monetary", "fiscal", "economic"),
}


def infer_subject(text: str) -> Subject:
    """§10: choose the visual grammar (graphs vs diagrams vs timelines vs code)."""
    t = (text or "").lower()
    best, score = Subject.GENERAL, 0
    for subj, keys in _SUBJECT_HINTS.items():
        n = sum(1 for k in keys if k in t)
        if n > score:
            best, score = subj, n
    return best


class TopicPlanner:
    async def build(self, topic: str, learner: LearnerProfile) -> KnowledgeGraph:
        subject = infer_subject(topic)
        data = await llm.json_call(
            SYSTEM,
            f"Topic: {topic}\nLearner level: {learner.level.value}\n"
            f"Available time: {learner.minutes} minutes\n"
            f"Objective: {learner.objective or 'solid working understanding'}\n"
            f"Prior knowledge: {learner.prior_knowledge or 'none stated'}\n"
            f"Produce {self._n_concepts(learner.minutes)} concepts.\n"
            'JSON: {"subject":"mathematics|physics|chemistry|biology|history|'
            'programming|economics|general","title":"","concepts":[{"id":"c0","name":"",'
            '"summary":"","notes":"120-200 words of teachable content","difficulty":0.3,'
            '"est_minutes":5,"prerequisites":[],"keywords":[""]}]}',
            fallback=None,
            temperature=0.35,
        )
        if isinstance(data, dict) and data.get("concepts"):
            kg = self._from_llm(data, topic, subject)
            if kg:
                return kg
        return self._fallback(topic, learner, subject)

    @staticmethod
    def _n_concepts(minutes: float) -> int:
        return max(3, min(10, int(minutes // 4) + 2))

    def _from_llm(self, data: dict, topic: str, subject: Subject) -> KnowledgeGraph | None:
        concepts: list[Concept] = []
        chunks: list[Chunk] = []
        doc_id = "topic-" + re.sub(r"\W+", "-", topic.lower())[:24]
        for i, raw in enumerate(data["concepts"][:12]):
            try:
                cid = str(raw.get("id") or f"c{i}")
                notes = str(raw.get("notes") or raw.get("summary") or "").strip()
                if len(notes) < 40:
                    continue
                # Generated notes become the retrieval corpus -> Agent 2 stays grounded.
                ch = Chunk(id=f"{doc_id}-{cid}", doc_id=doc_id, text=notes, page=i + 1,
                           section=str(raw.get("name", f"Concept {i+1}"))[:80])
                chunks.append(ch)
                concepts.append(
                    Concept(
                        id=cid,
                        name=str(raw.get("name", f"Concept {i+1}"))[:90],
                        summary=str(raw.get("summary", notes[:200]))[:500],
                        difficulty=float(raw.get("difficulty", 0.3 + 0.06 * i)),
                        est_minutes=float(raw.get("est_minutes", 5)),
                        prerequisites=[str(p) for p in raw.get("prerequisites", [])],
                        chunk_ids=[ch.id],
                        keywords=[str(k) for k in raw.get("keywords", [])][:8],
                    )
                )
            except Exception:
                continue
        if len(concepts) < 3:
            return None
        store.add(chunks)
        ContextAgent._validate_dag(concepts)
        try:
            subj = Subject(str(data.get("subject", subject.value)))
        except ValueError:
            subj = subject
        return KnowledgeGraph(
            doc_id=doc_id,
            concepts=concepts,
            order=topological_order(concepts),
            subject=subj.value,
            title=str(data.get("title") or topic)[:120],
            source="topic",
        )

    def _fallback(self, topic: str, learner: LearnerProfile, subject: Subject
                  ) -> KnowledgeGraph:
        """Offline: a pedagogically-shaped generic scaffold (Bloom progression).
        Honest about being a scaffold rather than inventing false facts."""
        stages = [
            ("Introduction and Motivation",
             f"What {topic} is, why it matters, and where it is used in practice."),
            ("Core Terminology",
             f"The vocabulary and definitions needed to discuss {topic} precisely."),
            ("Fundamental Principles",
             f"The central rules and mechanisms that govern {topic}."),
            ("Worked Examples",
             f"Step-by-step application of {topic} to concrete problems."),
            ("Common Pitfalls",
             f"Frequent misconceptions about {topic} and how to avoid them."),
            ("Advanced Applications",
             f"Where {topic} extends into real-world and advanced settings."),
        ]
        n = self._n_concepts(learner.minutes)
        doc_id = "topic-" + re.sub(r"\W+", "-", topic.lower())[:24]
        concepts, chunks = [], []
        for i, (name, desc) in enumerate(stages[:n]):
            body = (
                f"{desc} At the {learner.level.value} level this section builds directly on "
                f"the previous one. Note: an LLM API key enables fully generated study "
                f"notes for this topic."
            )
            ch = Chunk(id=f"{doc_id}-c{i}", doc_id=doc_id, text=body, page=i + 1, section=name)
            chunks.append(ch)
            concepts.append(
                Concept(
                    id=f"c{i}", name=f"{name}: {topic}"[:90], summary=desc,
                    difficulty=min(0.9, 0.2 + 0.13 * i),
                    est_minutes=max(2.0, learner.minutes / n),
                    prerequisites=[f"c{i-1}"] if i else [],
                    chunk_ids=[ch.id], keywords=topic.split()[:5],
                )
            )
        store.add(chunks)
        return KnowledgeGraph(
            doc_id=doc_id, concepts=concepts, order=[c.id for c in concepts],
            subject=subject.value, title=topic[:120], source="topic",
        )


topic_planner = TopicPlanner()

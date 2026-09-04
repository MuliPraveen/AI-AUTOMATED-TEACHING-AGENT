"""End-to-end tests. All run offline — no API keys, no network."""
from __future__ import annotations

import asyncio

import pytest

from app.agents.agent1_context import (
    ContextAgent,
    _creates_cycle,
    context_agent,
    topological_order,
)
from app.agents.agent2_teaching import teaching_agent
from app.agents.agent3_assessment import assessment_agent
from app.core.llm import parse_json
from app.core.orchestrator import orchestrator
from app.core.schemas import Concept, KnowledgeGraph, Question
from app.ingest.parser import chunk_document
from app.ingest.vector_store import VectorStore
from app.media.speech import estimate_timings, visemes

DOC = b"""# Gradient Descent
Gradient descent minimizes a loss function by stepping opposite to the gradient.
The parameters are updated each iteration scaled by the learning rate value.

# Learning Rate
The learning rate controls the step size of every optimizer update applied.
Too large a learning rate makes the optimization diverge and oscillate badly.

# Momentum
Momentum accumulates a decaying average of past gradients to accelerate descent.
It damps oscillations across steep ravines and speeds up consistent directions.
"""


# ------------------------------------------------------------------ parsing
def test_chunking_produces_sections():
    chunks = chunk_document("d", "notes.md", DOC)
    assert len(chunks) >= 3
    assert {c.section for c in chunks} >= {"Gradient Descent", "Learning Rate"}
    assert all(len(c.text) > 60 for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)  # ids unique


# ---------------------------------------------------------------- retrieval
def test_hybrid_search_ranks_correct_section():
    vs = VectorStore()
    vs.add(chunk_document("d", "notes.md", DOC))
    top = vs.search("learning rate too large diverge", k=2)
    assert top and top[0][0].section == "Learning Rate"


def test_search_empty_store_is_safe():
    assert VectorStore().search("anything") == []


# ---------------------------------------------------------------------- DAG
def test_topological_order_respects_prerequisites():
    cs = [
        Concept(id="a", name="A"),
        Concept(id="b", name="B", prerequisites=["a"]),
        Concept(id="c", name="C", prerequisites=["b"]),
    ]
    order = topological_order(cs)
    assert order.index("a") < order.index("b") < order.index("c")


def test_cycles_are_removed():
    cs = [
        Concept(id="a", name="A", prerequisites=["b"]),
        Concept(id="b", name="B", prerequisites=["a"]),
    ]
    ContextAgent._validate_dag(cs)
    assert not (cs[0].prerequisites and cs[1].prerequisites)
    assert len(topological_order(cs)) == 2


def test_cycle_detector():
    # edges map prerequisite -> dependents:  a -> b -> c
    edges = {"a": {"b"}, "b": {"c"}}
    # giving "a" the prerequisite "c" would close the loop a->b->c->a
    assert _creates_cycle(edges, "a", "c")
    # an unrelated node introduces no cycle
    assert not _creates_cycle(edges, "a", "d")


# ------------------------------------------------------------------ planner
def test_plan_respects_time_budget_and_orders_by_dag():
    kg = KnowledgeGraph(
        doc_id="d",
        concepts=[
            Concept(id="a", name="A", difficulty=0.2),
            Concept(id="b", name="B", difficulty=0.9, prerequisites=["a"]),
        ],
        order=["a", "b"],
    )
    plan = teaching_agent.plan("s", kg, total_minutes=20)
    assert abs(sum(i.minutes for i in plan.items) - 20) < 0.5
    assert [i.concept_id for i in plan.items] == ["a", "b"]
    # harder concept gets more time
    assert plan.items[1].minutes >= plan.items[0].minutes


# --------------------------------------------------------------- assessment
def test_mcq_grading_and_misconception_mapping():
    q = Question(
        id="q", concept_id="a", prompt="p", options=["right", "wrong"],
        answer_index=0, distractor_map={"1": "sign-error"},
    )
    ok = asyncio.run(assessment_agent.evaluate(q, 0))
    bad = asyncio.run(assessment_agent.evaluate(q, 1))
    assert ok.correct and ok.score == 1.0 and not ok.remediate
    assert not bad.correct and bad.misconception == "sign-error" and bad.remediate


def test_mastery_converges_and_resists_single_guess():
    from app.core.schemas import StudentProfile

    kg = KnowledgeGraph(doc_id="d", concepts=[Concept(id="a", name="A")], order=["a"])
    p = StudentProfile(session_id="s")
    q = Question(id="q", concept_id="a", prompt="p", options=["r", "w"], answer_index=0)
    wrong = asyncio.run(assessment_agent.evaluate(q, 1))
    assessment_agent.update_profile(p, kg, wrong, "A")
    assert p.mastery["a"].mastery == 0.0 and "A" in p.gaps
    for _ in range(4):
        right = asyncio.run(assessment_agent.evaluate(q, 0))
        assessment_agent.update_profile(p, kg, right, "A")
    assert p.mastery["a"].mastery > 0.7  # recovers, but not instantly
    assert p.overall > 0.7


def test_next_steps_recommend_prerequisite_first():
    from app.core.schemas import StudentProfile

    kg = KnowledgeGraph(
        doc_id="d",
        concepts=[Concept(id="a", name="Basics"),
                  Concept(id="b", name="Advanced", prerequisites=["a"])],
        order=["a", "b"],
    )
    p = StudentProfile(session_id="s")
    for cid, name in (("a", "Basics"), ("b", "Advanced")):
        q = Question(id=f"q{cid}", concept_id=cid, prompt="p",
                     options=["r", "w"], answer_index=0)
        ev = asyncio.run(assessment_agent.evaluate(q, 1))
        assessment_agent.update_profile(p, kg, ev, name)
    assert any("Basics" in s and "Advanced" in s for s in p.next_steps)


# --------------------------------------------------------------------- media
def test_timings_and_visemes_are_monotonic():
    t = estimate_timings("Hello there, this is a test. And another sentence!")
    assert t and all(a["end"] <= b["end"] for a, b in zip(t, t[1:]))
    assert all(t[i]["char"] < t[i + 1]["char"] for i in range(len(t) - 1))
    v = visemes(t)
    assert v and all(a["t"] <= b["t"] for a, b in zip(v, v[1:]))


# ----------------------------------------------------------------- json repair
@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"a":1}', {"a": 1}),
        ('```json\n{"a":1}\n```', {"a": 1}),
        ('here you go: {"a":1} hope that helps', {"a": 1}),
        ("total garbage", None),
    ],
)
def test_json_repair(raw, expected):
    assert parse_json(raw, None) == expected


# ------------------------------------------------------------------ e2e loop
def test_full_session_offline():
    async def run():
        s = orchestrator.create(total_minutes=12)
        kg = await orchestrator.ingest(s.id, "notes.md", DOC)
        assert len(kg.concepts) >= 3 and s.plan
        turn = await orchestrator.next_turn(s.id)
        assert turn["narration"] and turn["audio"]["duration"] > 0
        assert turn["avatar"]["mode"] == "canvas"
        assert s.pending is not None
        ev = await orchestrator.answer(s.id, s.pending.answer_index)
        assert ev.correct
        guard = 0
        while await orchestrator.next_turn(s.id) is not None and guard < 20:
            guard += 1
            if s.pending:
                await orchestrator.answer(s.id, s.pending.answer_index)
        assert s.state.value == "complete"
        assert s.profile.overall > 0
        return s

    s = asyncio.run(run())
    assert s.queue.qsize() > 0  # events were streamed


def test_remediation_triggers_on_wrong_answer():
    async def run():
        s = orchestrator.create(total_minutes=10)
        await orchestrator.ingest(s.id, "notes.md", DOC)
        await orchestrator.next_turn(s.id)
        cid = s.pending.concept_id
        wrong = 1 if s.pending.answer_index != 1 else 0
        await orchestrator.answer(s.id, wrong)
        assert s.remediated.get(cid) == 1
        return s

    asyncio.run(run())

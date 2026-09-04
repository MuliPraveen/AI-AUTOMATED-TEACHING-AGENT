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
from app.core.schemas import Concept, KnowledgeGraph, LearnerProfile, Level, Question
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
        s = orchestrator.create(LearnerProfile(minutes=12))
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
        s = orchestrator.create(LearnerProfile(minutes=10))
        await orchestrator.ingest(s.id, "notes.md", DOC)
        await orchestrator.next_turn(s.id)
        cid = s.pending.concept_id
        wrong = 1 if s.pending.answer_index != 1 else 0
        await orchestrator.answer(s.id, wrong)
        assert s.remediated.get(cid) == 1
        return s

    asyncio.run(run())


# ============================================================================
# Round-2 mandatory requirements (§3, §4, §6, §8, §10, §12, §13)
# ============================================================================
from app.agents.topic_planner import infer_subject, topic_planner  # noqa: E402
from app.core import i18n  # noqa: E402
from app.core.schemas import Subject  # noqa: E402


# ------------------------------------------------- §3 DOCX / PPTX ingest ---
def _docx_bytes(paras):
    import io, zipfile
    body = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>{t}</w:t></w:r></w:p>'
        if h else f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>"
        for t, h in paras
    )
    xml = ('<?xml version="1.0"?><w:document xmlns:w="x"><w:body>' + body +
           "</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def _pptx_bytes(slides):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i, runs in enumerate(slides, 1):
            body = "".join(f"<a:t>{r}</a:t>" for r in runs)
            z.writestr(f"ppt/slides/slide{i}.xml", f'<p:sld xmlns:a="x">{body}</p:sld>')
    return buf.getvalue()


def test_docx_ingest_recovers_headings():
    data = _docx_bytes([
        ("Photosynthesis", True),
        ("Photosynthesis converts light energy into chemical energy inside chloroplasts "
         "using carbon dioxide and water to produce glucose and oxygen for the plant.", False),
        ("Respiration", True),
        ("Cellular respiration releases the stored energy of glucose to make ATP, which "
         "powers nearly every active process inside a living animal or plant cell.", False),
    ])
    chunks = chunk_document("d", "bio.docx", data)
    assert chunks and {c.section for c in chunks} >= {"Photosynthesis", "Respiration"}


def test_pptx_ingest_one_page_per_slide():
    data = _pptx_bytes([
        ["Newton's First Law",
         "An object at rest stays at rest unless acted upon by an external unbalanced force "
         "acting on that object in some measurable direction."],
        ["Newton's Second Law",
         "The net force acting on a body equals its mass multiplied by the acceleration "
         "produced, which is the basis of nearly all classical dynamics problems."],
    ])
    chunks = chunk_document("d", "physics.pptx", data)
    assert chunks and any("Newton" in c.section for c in chunks)


# ------------------------------------------------- §4 topic-based teaching --
def test_topic_mode_builds_valid_dag_offline():
    from app.core.schemas import LearnerProfile as LP

    kg = asyncio.run(topic_planner.build("Newton's Laws of Motion", LP(minutes=20)))
    assert kg.source == "topic"
    assert len(kg.concepts) >= 3
    assert len(kg.order) == len(kg.concepts)
    # every concept is grounded by at least one retrievable chunk
    from app.ingest.vector_store import store as gstore
    assert all(gstore.by_ids(c.chunk_ids) for c in kg.concepts)
    # order respects prerequisites
    pos = {cid: i for i, cid in enumerate(kg.order)}
    for c in kg.concepts:
        for p in c.prerequisites:
            assert pos[p] < pos[c.id]


def test_topic_session_end_to_end_offline():
    from app.core.schemas import LearnerProfile as LP

    async def run():
        s = orchestrator.create(LP(minutes=10, level=Level.BEGINNER))
        kg = await orchestrator.from_topic(s.id, "Photosynthesis")
        assert kg.source == "topic" and s.plan
        turn = await orchestrator.next_turn(s.id)
        assert turn and turn["narration"]
        return s

    asyncio.run(run())


# ------------------------------------------- §10 subject-aware visuals -----
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Teach me integral calculus and the fundamental theorem", Subject.MATH),
        ("Newton's laws of motion and force", Subject.PHYSICS),
        ("photosynthesis in the plant cell and dna", Subject.BIOLOGY),
        ("React hooks and javascript api design", Subject.PROGRAMMING),
        ("the Mughal empire and the 1857 revolution", Subject.HISTORY),
    ],
)
def test_subject_inference(text, expected):
    assert infer_subject(text) == expected


def test_visual_grammar_matches_subject():
    from app.agents.agent2_teaching import teaching_agent as ta

    c = Concept(id="c0", name="Binary Search", summary="Halve the range each step.")
    assert ta._default_visual(c, "programming", "x" * 400).type.value == "code"
    assert ta._default_visual(c, "history", "x" * 400).type.value == "mermaid"


# ---------------------------------------------------- §8 multilingual ------
@pytest.mark.parametrize(
    "raw,code",
    [("hi", "hi"), ("Hindi", "hi"), ("हिन्दी", "hi"), ("hinglish", "hi-en"),
     ("Tamil", "ta"), ("en-US", "en"), ("klingon", "en")],
)
def test_language_resolution(raw, code):
    assert i18n.resolve(raw)[0] == code


@pytest.mark.parametrize(
    "utterance,code",
    [
        ("Explain this topic in Hindi", "hi"),
        ("Now explain it in English", "en"),
        ("Mujhe ye Hinglish mein simple example ke saath samjhao", "hi-en"),
        ("can you switch to Tamil please", "ta"),
        ("what is the derivative of x squared", None),
    ],
)
def test_natural_language_switch_detection(utterance, code):
    got = i18n.detect_switch(utterance)
    assert (got[0] if got else None) == code


def test_dense_scripts_get_slower_speaking_rate():
    assert i18n.wpm_for("hi") < i18n.wpm_for("en")
    t_en = estimate_timings("this is a test of the timing track", language="en")
    t_hi = estimate_timings("this is a test of the timing track", language="hi")
    assert t_hi[-1]["end"] > t_en[-1]["end"]


def test_language_switch_preserves_lesson_context():
    """§8: changing language must NOT reset pedagogical state."""
    from app.core.schemas import LearnerProfile as LP

    async def run():
        s = orchestrator.create(LP(minutes=10))
        await orchestrator.ingest(s.id, "notes.md", DOC)
        await orchestrator.next_turn(s.id)
        cursor, plan, mastery = s.cursor, s.plan, dict(s.profile.mastery)
        code, name = await orchestrator.set_language(s.id, "Hindi")
        assert (code, name) == ("hi", "Hindi")
        assert s.cursor == cursor and s.plan is plan
        assert dict(s.profile.mastery) == mastery
        assert s.kg is not None  # graph intact
        return s

    asyncio.run(run())


# --------------------------------------------- §6 level personalization ----
def test_level_changes_prompt_style():
    from app.agents.agent2_teaching import LEVEL_STYLE

    assert "BEGINNER" in LEVEL_STYLE[Level.BEGINNER]
    assert "ADVANCED" in LEVEL_STYLE[Level.ADVANCED]
    assert LEVEL_STYLE[Level.BEGINNER] != LEVEL_STYLE[Level.ADVANCED]


# ----------------------------------------- §7 time-based lesson shaping ----
@pytest.mark.parametrize("minutes", [5, 20, 60])
def test_time_budget_shapes_lesson(minutes):
    kg = KnowledgeGraph(
        doc_id="d",
        concepts=[Concept(id=f"c{i}", name=f"C{i}", difficulty=0.3 + i * 0.1)
                  for i in range(5)],
        order=[f"c{i}" for i in range(5)],
    )
    plan = teaching_agent.plan("s", kg, total_minutes=minutes)
    assert abs(sum(i.minutes for i in plan.items) - minutes) < 1.0


def test_longer_sessions_go_deeper():
    kg = KnowledgeGraph(
        doc_id="d",
        concepts=[Concept(id="a", name="A"), Concept(id="b", name="B")],
        order=["a", "b"],
    )
    short = teaching_agent.plan("s", kg, total_minutes=5)
    long = teaching_agent.plan("s", kg, total_minutes=60)
    depths = ["overview", "standard", "deep"]
    assert depths.index(long.items[0].depth.value) > depths.index(short.items[0].depth.value)


# ----------------------------- §12 multi-attempt adaptive re-explanation ---
def test_two_remediation_attempts_then_move_on():
    from app.core.schemas import LearnerProfile as LP

    async def run():
        s = orchestrator.create(LP(minutes=10))
        await orchestrator.ingest(s.id, "notes.md", DOC)
        await orchestrator.next_turn(s.id)
        cid = s.pending.concept_id
        for _ in range(4):
            if not s.pending:
                break
            wrong = 1 if s.pending.answer_index != 1 else 0
            await orchestrator.answer(s.id, wrong)
        assert s.remediated.get(cid) == 2  # capped, lesson continues
        return s

    asyncio.run(run())


# ------------------------------------------------ §13 learning report ------
def test_learning_report_shape():
    from app.core.schemas import LearnerProfile as LP

    async def run():
        s = orchestrator.create(LP(minutes=10))
        await orchestrator.ingest(s.id, "notes.md", DOC)
        await orchestrator.next_turn(s.id)
        wrong = 1 if s.pending.answer_index != 1 else 0
        await orchestrator.answer(s.id, wrong)
        return orchestrator.build_report(s)

    r = asyncio.run(run())
    assert 0 <= r.score_pct <= 100
    assert r.grade in {"A", "B", "C", "D", "E"}
    assert r.suggested_next_topic and r.summary
    assert r.weak_areas or r.concepts_understood


def test_subject_inferred_from_body_not_just_titles():
    """Terse headings ('Current', 'Resistance') must still resolve to physics."""
    from app.core.schemas import LearnerProfile as LP

    doc = (b"# Current\nElectric current is the flow of charge measured in amperes "
           b"through a conductor when a voltage is applied across its two ends.\n\n"
           b"# Resistance\nResistance in ohms opposes the flow of current and depends "
           b"on the material, its length and its cross sectional area in a circuit.\n")

    async def run():
        s = orchestrator.create(LP(minutes=8))
        return await orchestrator.ingest(s.id, "elec.docx", doc)

    assert asyncio.run(run()).subject == "physics"


def test_mislabeled_extension_falls_back_to_text():
    """A .docx name with plain-text bytes must not crash the ingest."""
    chunks = chunk_document("d", "actually_text.docx", DOC)
    assert chunks and any("Gradient" in c.text or "gradient" in c.text for c in chunks)


def test_scanned_pdf_without_text_layer_raises_clean_error():
    """No extractable text -> a 422-able ValueError, not a stack trace."""
    from app.core.schemas import LearnerProfile as LP

    async def run():
        s = orchestrator.create(LP(minutes=5))
        await orchestrator.ingest(s.id, "blank.txt", b"   \n\n  ")

    with pytest.raises(ValueError):
        asyncio.run(run())

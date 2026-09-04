"""Backend Orchestrator — an explicit finite state machine over the three agents.

    IDLE -> INGESTING -> PLANNING -> TEACHING -> ASSESSING
                                        ^            |
                                        |            v
                                        +------ REMEDIATING --> ... -> COMPLETE

Every transition emits a typed WSEvent, so the frontend is a pure function of
the event stream (easy to replay, log and debug during a demo).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.agents.agent1_context import context_agent
from app.agents.agent2_teaching import teaching_agent
from app.agents.agent3_assessment import assessment_agent
from app.agents.topic_planner import infer_subject, topic_planner
from app.core import i18n
from app.core.schemas import (
    Evaluation,
    KnowledgeGraph,
    LearnerProfile,
    LearningReport,
    LessonPlan,
    Question,
    SessionState,
    StudentProfile,
    TeachingTurn,
    WSEvent,
)
from app.media.avatar import avatar
from app.media.speech import speech

MAX_REMEDIATION = 2  # §12: up to two alternative explanations before moving on


@dataclass
class Session:
    id: str
    state: SessionState = SessionState.IDLE
    kg: KnowledgeGraph | None = None
    plan: LessonPlan | None = None
    profile: StudentProfile = field(default_factory=lambda: StudentProfile(session_id=""))
    learner: LearnerProfile = field(default_factory=LearnerProfile)
    cursor: int = 0
    pending: Question | None = None
    remediated: dict[str, int] = field(default_factory=dict)
    queue: asyncio.Queue[WSEvent] = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    created: float = field(default_factory=time.time)
    total_minutes: float = 20.0
    taught_minutes: float = 0.0

    async def emit(self, type_: str, **payload: Any) -> None:
        ev = WSEvent(type=type_, payload=payload)
        try:
            self.queue.put_nowait(ev)
        except asyncio.QueueFull:  # slow client: drop oldest, never block teaching
            _ = self.queue.get_nowait()
            self.queue.put_nowait(ev)

    async def set_state(self, s: SessionState) -> None:
        self.state = s
        await self.emit("state", state=s.value)


class Orchestrator:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}

    # ------------------------------------------------------------ session --
    def create(self, learner: LearnerProfile | None = None) -> Session:
        learner = learner or LearnerProfile()
        sid = uuid.uuid4().hex[:12]
        s = Session(id=sid, total_minutes=learner.minutes, learner=learner)
        s.profile = StudentProfile(session_id=sid)
        self.sessions[sid] = s
        return s

    def get(self, sid: str) -> Session:
        if sid not in self.sessions:
            raise KeyError(f"unknown session {sid}")
        return self.sessions[sid]

    # ------------------------------------------------------------ ingest ---
    async def ingest(self, sid: str, filename: str, data: bytes) -> KnowledgeGraph:
        """Entry point A (§3): learn from an uploaded document."""
        s = self.get(sid)
        await s.set_state(SessionState.INGESTING)
        doc_id, kg = await context_agent.ingest(filename, data)
        s.kg = kg
        return await self._after_knowledge(s, kg, doc_id)

    async def from_topic(self, sid: str, topic: str) -> KnowledgeGraph:
        """Entry point B (§4): teach a topic with no uploaded material."""
        s = self.get(sid)
        await s.set_state(SessionState.INGESTING)
        kg = await topic_planner.build(topic, s.learner)
        s.kg = kg
        return await self._after_knowledge(s, kg, kg.doc_id)

    async def _after_knowledge(self, s: Session, kg: KnowledgeGraph, doc_id: str
                               ) -> KnowledgeGraph:
        """Shared tail: both entry points converge on the same planning path."""
        if kg.subject == "general":
            # Infer from names AND body text — titles alone are often too terse.
            corpus = (
                f"{kg.title} "
                + " ".join(c.name for c in kg.concepts)
                + " "
                + " ".join(c.summary[:400] for c in kg.concepts)
            )
            kg.subject = infer_subject(corpus).value
        await s.emit("knowledge_graph", doc_id=doc_id, graph=kg.model_dump())
        await s.set_state(SessionState.PLANNING)
        s.plan = teaching_agent.plan(s.id, kg, s.total_minutes, s.profile)
        await s.emit("lesson_plan", plan=s.plan.model_dump(),
                     learner=s.learner.model_dump())
        return kg

    async def set_language(self, sid: str, code_or_name: str) -> tuple[str, str]:
        """§8: switch teaching language mid-lesson without losing context."""
        s = self.get(sid)
        code, name = i18n.resolve(code_or_name)
        s.learner.language, s.learner.language_name = code, name
        await s.emit("language_changed", code=code, name=name)
        return code, name

    # ------------------------------------------------------------- teach ---
    async def next_turn(self, sid: str) -> dict | None:
        """Advance the FSM one step: deliver the next concept (or finish)."""
        s = self.get(sid)
        if not (s.kg and s.plan):
            raise RuntimeError("ingest a document first")
        if s.cursor >= len(s.plan.items):
            await self._finish(s)
            return None

        await s.set_state(SessionState.TEACHING)
        item = s.plan.items[s.cursor]
        concept = next(c for c in s.kg.concepts if c.id == item.concept_id)
        turn = await teaching_agent.teach(
            concept, item, learner=s.learner, subject=s.kg.subject
        )
        payload = await self._render(s, turn, item)
        s.taught_minutes += item.minutes
        s.cursor += 1
        s.pending = turn.check_question
        if s.pending:
            await s.set_state(SessionState.ASSESSING)
            await s.emit("question", question=s.pending.model_dump())
        return payload

    async def _render(self, s: Session, turn: TeachingTurn, item) -> dict:
        """Fan out TTS + avatar concurrently, then emit one synchronized payload."""
        audio = await speech.synthesize(turn.narration, language=s.learner.language)
        av = await avatar.frame_source(audio.get("audio_url"), turn.narration)
        payload = {
            "concept_id": turn.concept_id,
            "concept": item.name,
            "depth": item.depth.value,
            "minutes": item.minutes,
            "language": s.learner.language,
            "level": s.learner.level.value,
            "subject": s.kg.subject if s.kg else "general",
            "narration": turn.narration,
            "blocks": [b.model_dump() for b in turn.blocks],
            "audio": audio,
            "avatar": av,
            "progress": {"index": s.cursor + 1, "total": len(s.plan.items) if s.plan else 0},
        }
        await s.emit("teaching_turn", **payload)
        return payload

    # ------------------------------------------------------------ answer ---
    async def answer(self, sid: str, answer: str | int) -> Evaluation:
        s = self.get(sid)
        if not s.pending or not s.kg:
            raise RuntimeError("no question pending")
        q = s.pending
        ev = await assessment_agent.evaluate(q, answer)
        name = next((c.name for c in s.kg.concepts if c.id == q.concept_id), q.concept_id)
        assessment_agent.update_profile(s.profile, s.kg, ev, name)
        s.pending = None
        await s.emit("evaluation", evaluation=ev.model_dump(),
                     profile=s.profile.model_dump())

        if ev.remediate and s.remediated.get(q.concept_id, 0) < MAX_REMEDIATION:
            s.remediated[q.concept_id] = s.remediated.get(q.concept_id, 0) + 1
            await self._remediate(s, q.concept_id, ev.misconception or "unclear understanding")
        else:
            # Adaptive re-plan: redistribute the remaining budget by live mastery.
            self._replan_tail(s)
        return ev

    async def _remediate(self, s: Session, concept_id: str, misconception: str) -> None:
        await s.set_state(SessionState.REMEDIATING)
        assert s.kg and s.plan
        concept = next(c for c in s.kg.concepts if c.id == concept_id)
        item = next(i for i in s.plan.items if i.concept_id == concept_id)
        attempt = s.remediated.get(concept_id, 1) - 1
        # §12: re-explain shorter and simpler each time, with a fresh analogy.
        simpler = item.model_copy(update={"minutes": max(1.5, item.minutes * 0.6)})
        turn = await teaching_agent.teach(
            concept, simpler, remediation=misconception,
            learner=s.learner, subject=s.kg.subject, attempt=attempt,
        )
        await self._render(s, turn, simpler)
        if turn.check_question:
            s.pending = turn.check_question
            await s.set_state(SessionState.ASSESSING)
            await s.emit("question", question=s.pending.model_dump())

    def _replan_tail(self, s: Session) -> None:
        """Re-allocate only the *unteached* remainder, preserving history."""
        if not (s.kg and s.plan) or s.cursor >= len(s.plan.items):
            return
        spent = sum(i.minutes for i in s.plan.items[: s.cursor])
        remaining = max(2.0, s.plan.total_minutes - spent)
        tail_ids = {i.concept_id for i in s.plan.items[s.cursor :]}
        sub = KnowledgeGraph(
            doc_id=s.kg.doc_id,
            concepts=[c for c in s.kg.concepts if c.id in tail_ids],
            order=[c for c in s.kg.order if c in tail_ids],
        )
        new_tail = teaching_agent.plan(s.id, sub, remaining, s.profile)
        s.plan.items = s.plan.items[: s.cursor] + new_tail.items

    # ------------------------------------------------------------ finish ---
    async def _finish(self, s: Session) -> None:
        await s.set_state(SessionState.COMPLETE)
        assert s.kg
        quiz = await assessment_agent.final_quiz(s.kg, s.profile, learner=s.learner)
        report = self.build_report(s)
        await s.emit(
            "session_complete",
            profile=s.profile.model_dump(),
            quiz=[q.model_dump() for q in quiz],
            report=report.model_dump(),
        )

    def build_report(self, s: Session) -> LearningReport:
        """§13 Assessment and Feedback — the end-of-lesson learning report."""
        assert s.kg
        p = s.profile
        pct = int(round(p.overall * 100))
        grade = ("A" if pct >= 90 else "B" if pct >= 75 else "C" if pct >= 60
                 else "D" if pct >= 40 else "E")
        mis = sorted({m for cm in p.mastery.values() for m in cm.misconceptions})
        incorrect = [cm.name for cm in p.mastery.values() if cm.score < 0.5]
        taught = {i.concept_id for i in (s.plan.items[: s.cursor] if s.plan else [])}
        untaught = [c.name for c in s.kg.concepts if c.id not in taught]
        nxt = (
            untaught[0] if untaught
            else (p.gaps[0] if p.gaps else "Applied practice problems on " +
                  (s.kg.title or "this material"))
        )
        summary = (
            f"You scored {pct}% across {len(p.mastery)} assessed concept(s). "
            + (f"Strong on {', '.join(p.strengths[:3])}. " if p.strengths else "")
            + (f"Needs work: {', '.join(p.gaps[:3])}. " if p.gaps
               else "No significant gaps detected. ")
            + (f"Watch out for the '{mis[0].replace('-', ' ')}' misconception."
               if mis else "")
        )
        return LearningReport(
            topic=s.kg.title or "Uploaded material",
            score_pct=pct,
            grade=grade,
            concepts_understood=p.strengths,
            weak_areas=p.gaps,
            incorrect_concepts=incorrect,
            misconceptions=mis,
            recommended_revision=p.next_steps,
            suggested_next_topic=nxt,
            time_spent_minutes=round(s.taught_minutes, 1),
            summary=summary,
        )

    # -------------------------------------------------------------- stream -
    async def stream(self, sid: str) -> AsyncIterator[WSEvent]:
        s = self.get(sid)
        while True:
            ev = await s.queue.get()
            yield ev


orchestrator = Orchestrator()

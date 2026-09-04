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
from app.core.schemas import (
    Evaluation,
    KnowledgeGraph,
    LessonPlan,
    Question,
    SessionState,
    StudentProfile,
    TeachingTurn,
    WSEvent,
)
from app.media.avatar import avatar
from app.media.speech import speech

MAX_REMEDIATION = 1  # per concept, keeps the session inside its time budget


@dataclass
class Session:
    id: str
    state: SessionState = SessionState.IDLE
    kg: KnowledgeGraph | None = None
    plan: LessonPlan | None = None
    profile: StudentProfile = field(default_factory=lambda: StudentProfile(session_id=""))
    cursor: int = 0
    pending: Question | None = None
    remediated: dict[str, int] = field(default_factory=dict)
    queue: asyncio.Queue[WSEvent] = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    created: float = field(default_factory=time.time)
    total_minutes: float = 20.0

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
    def create(self, total_minutes: float = 20.0) -> Session:
        sid = uuid.uuid4().hex[:12]
        s = Session(id=sid, total_minutes=total_minutes)
        s.profile = StudentProfile(session_id=sid)
        self.sessions[sid] = s
        return s

    def get(self, sid: str) -> Session:
        if sid not in self.sessions:
            raise KeyError(f"unknown session {sid}")
        return self.sessions[sid]

    # ------------------------------------------------------------ ingest ---
    async def ingest(self, sid: str, filename: str, data: bytes) -> KnowledgeGraph:
        s = self.get(sid)
        await s.set_state(SessionState.INGESTING)
        doc_id, kg = await context_agent.ingest(filename, data)
        s.kg = kg
        await s.emit("knowledge_graph", doc_id=doc_id, graph=kg.model_dump())

        await s.set_state(SessionState.PLANNING)
        s.plan = teaching_agent.plan(sid, kg, s.total_minutes, s.profile)
        await s.emit("lesson_plan", plan=s.plan.model_dump())
        return kg

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
        turn = await teaching_agent.teach(concept, item)
        payload = await self._render(s, turn, item)
        s.cursor += 1
        s.pending = turn.check_question
        if s.pending:
            await s.set_state(SessionState.ASSESSING)
            await s.emit("question", question=s.pending.model_dump())
        return payload

    async def _render(self, s: Session, turn: TeachingTurn, item) -> dict:
        """Fan out TTS + avatar concurrently, then emit one synchronized payload."""
        audio, _ = await asyncio.gather(
            speech.synthesize(turn.narration),
            asyncio.sleep(0),
        )
        av = await avatar.frame_source(audio.get("audio_url"), turn.narration)
        payload = {
            "concept_id": turn.concept_id,
            "concept": item.name,
            "depth": item.depth.value,
            "minutes": item.minutes,
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
        turn = await teaching_agent.teach(concept, item, remediation=misconception)
        await self._render(s, turn, item)
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
        quiz = await assessment_agent.final_quiz(s.kg, s.profile)
        await s.emit(
            "session_complete",
            profile=s.profile.model_dump(),
            quiz=[q.model_dump() for q in quiz],
        )

    # -------------------------------------------------------------- stream -
    async def stream(self, sid: str) -> AsyncIterator[WSEvent]:
        s = self.get(sid)
        while True:
            ev = await s.queue.get()
            yield ev


orchestrator = Orchestrator()

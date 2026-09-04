"""HTTP + WebSocket surface."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import (
    APIRouter,
    Body,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse

from app.core import i18n
from app.core.config import settings
from app.core.orchestrator import orchestrator
from app.core.schemas import LearnerProfile, Level
from app.media.avatar import avatar
from app.media.speech import AUDIO_DIR, speech

router = APIRouter()
MAX_UPLOAD = 25 * 1024 * 1024


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "version": settings.version,
        "capabilities": {
            "llm": settings.llm_enabled,
            "tts": settings.tts_enabled,
            "stt": settings.stt_enabled,
            "avatar_mode": avatar.mode,
        },
        "sessions": len(orchestrator.sessions),
    }


@router.get("/languages")
async def languages() -> dict:
    """§8: languages the AI Teacher can teach in."""
    return {"languages": [{"code": k, **v} for k, v in i18n.LANGUAGES.items()]}


def _learner_from(payload: dict) -> LearnerProfile:
    code, name = i18n.resolve(str(payload.get("language", "en")))
    try:
        level = Level(str(payload.get("level", "beginner")).lower())
    except ValueError:
        level = Level.BEGINNER
    return LearnerProfile(
        level=level,
        language=code,
        language_name=name,
        minutes=max(5.0, min(120.0, float(payload.get("minutes", 20)))),
        objective=str(payload.get("objective", ""))[:300],
        style=str(payload.get("style", ""))[:200],
        prior_knowledge=str(payload.get("prior_knowledge", ""))[:300],
    )


@router.post("/sessions")
async def create_session(payload: dict = Body(default={})) -> dict:
    """Create a session with the full learner profile (§6, §7, §8)."""
    learner = _learner_from(payload or {})
    s = orchestrator.create(learner)
    return {
        "session_id": s.id,
        "state": s.state.value,
        "total_minutes": s.total_minutes,
        "learner": learner.model_dump(),
    }


@router.post("/sessions/{sid}/topic")
async def teach_topic(sid: str, payload: dict = Body(...)):
    """§4 Topic-Based Learning — teach with no uploaded material."""
    topic = str(payload.get("topic", "")).strip()
    if not topic:
        raise HTTPException(400, "topic is required")
    try:
        s = orchestrator.get(sid)
    except KeyError:
        raise HTTPException(404, "session not found")
    kg = await orchestrator.from_topic(sid, topic[:200])
    return {
        "doc_id": kg.doc_id,
        "concepts": len(kg.concepts),
        "subject": kg.subject,
        "graph": kg.model_dump(),
        "plan": s.plan.model_dump() if s.plan else None,
    }


@router.post("/sessions/{sid}/language")
async def set_language(sid: str, payload: dict = Body(...)):
    """§8: switch teaching language mid-lesson, preserving lesson context."""
    try:
        code, name = await orchestrator.set_language(
            sid, str(payload.get("language", "en"))
        )
    except KeyError:
        raise HTTPException(404, "session not found")
    return {"language": code, "language_name": name}


@router.get("/sessions/{sid}/report")
async def report(sid: str):
    """§13 learning report — available at any point in the session."""
    try:
        s = orchestrator.get(sid)
    except KeyError:
        raise HTTPException(404, "session not found")
    if not s.kg:
        raise HTTPException(409, "nothing taught yet")
    return orchestrator.build_report(s).model_dump()


@router.post("/sessions/{sid}/ingest")
async def ingest(sid: str, file: UploadFile = File(...), minutes: float = Form(20.0)) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large (max 25MB)")
    try:
        s = orchestrator.get(sid)
    except KeyError:
        raise HTTPException(404, "session not found")
    if minutes:
        s.total_minutes = max(5.0, min(120.0, minutes))
        s.learner.minutes = s.total_minutes
    try:
        kg = await orchestrator.ingest(sid, file.filename or "doc.txt", data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {
        "doc_id": kg.doc_id,
        "concepts": len(kg.concepts),
        "graph": kg.model_dump(),
        "plan": s.plan.model_dump() if s.plan else None,
    }


@router.post("/sessions/{sid}/next")
async def next_turn(sid: str):
    try:
        turn = await orchestrator.next_turn(sid)
    except KeyError:
        raise HTTPException(404, "session not found")
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return JSONResponse(turn or {"done": True})


@router.post("/sessions/{sid}/answer")
async def answer(sid: str, payload: dict = Body(...)):
    try:
        ev = await orchestrator.answer(sid, payload.get("answer", ""))
    except KeyError:
        raise HTTPException(404, "session not found")
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    s = orchestrator.get(sid)
    return {"evaluation": ev.model_dump(), "profile": s.profile.model_dump()}


@router.post("/sessions/{sid}/ask")
async def ask(sid: str, payload: dict = Body(...)):
    """Student interrupts with a spoken/typed question -> grounded answer + TTS."""
    from app.agents.agent2_teaching import teaching_agent
    from app.core.llm import llm
    from app.ingest.vector_store import store

    question = str(payload.get("question", "")).strip()
    if not question:
        raise HTTPException(400, "empty question")
    s0 = orchestrator.get(sid)
    if (sw := i18n.detect_switch(question)):
        await orchestrator.set_language(sid, sw[0])
    hits = store.search(question, k=4)
    ctx = "\n\n".join(f"(p{c.page}) {c.text}" for c, _ in hits)
    text = await llm.json_call(
        "Answer the student's question using ONLY the context. Spoken prose, 3-5 sentences. "
        "Maintain the lesson context. "
        + i18n.instruction_for(s0.learner.language, s0.learner.language_name),
        f"Context:\n{ctx}\n\nQuestion: {question}\nJSON: {{\"answer\":\"\"}}",
        fallback=None,
    )
    ans = (
        text.get("answer")
        if isinstance(text, dict) and text.get("answer")
        else (
            f"Here's what the material says about that. "
            + teaching_agent._sanitize(ctx[:700])
            if ctx
            else "That isn't covered in this document — let's stay with the current concept."
        )
    )
    audio = await speech.synthesize(ans, language=s0.learner.language)
    s = s0
    await s.emit("answer", question=question, answer=ans, audio=audio,
                 citations=[{"page": c.page, "section": c.section} for c, _ in hits])
    return {"answer": ans, "audio": audio}


@router.post("/sessions/{sid}/transcribe")
async def transcribe(sid: str, file: UploadFile = File(...)):
    try:
        lang = orchestrator.get(sid).learner.language
    except KeyError:
        lang = "en"
    text = await speech.transcribe(
        await file.read(), file.content_type or "audio/webm", language=lang
    )
    switch = i18n.detect_switch(text)
    if switch:
        await orchestrator.set_language(sid, switch[0])
    return {"transcript": text, "language_switch": switch[0] if switch else None}


@router.get("/sessions/{sid}/profile")
async def profile(sid: str):
    try:
        return orchestrator.get(sid).profile.model_dump()
    except KeyError:
        raise HTTPException(404, "session not found")


@router.get("/media/audio/{name}")
async def audio(name: str):
    path = (AUDIO_DIR / name).resolve()
    if not str(path).startswith(str(AUDIO_DIR.resolve())) or not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type="audio/mpeg")


@router.websocket("/ws/{sid}")
async def ws(websocket: WebSocket, sid: str):
    await websocket.accept()
    try:
        session = orchestrator.get(sid)
    except KeyError:
        await websocket.send_text(json.dumps({"type": "error",
                                              "payload": {"message": "unknown session"}}))
        await websocket.close()
        return

    await websocket.send_text(json.dumps({"type": "state",
                                          "payload": {"state": session.state.value}}))

    async def pump() -> None:
        async for ev in orchestrator.stream(sid):
            await websocket.send_text(ev.model_dump_json())

    task = asyncio.create_task(pump())
    try:
        while True:  # client -> server control channel
            msg = json.loads(await websocket.receive_text())
            kind = msg.get("type")
            if kind == "next":
                asyncio.create_task(orchestrator.next_turn(sid))
            elif kind == "answer":
                asyncio.create_task(orchestrator.answer(sid, msg.get("answer", "")))
            elif kind == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "payload": {}}))
    except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
        pass
    finally:
        task.cancel()

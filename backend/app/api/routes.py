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

from app.core.config import settings
from app.core.orchestrator import orchestrator
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


@router.post("/sessions")
async def create_session(minutes: float = Body(20.0, embed=True)) -> dict:
    s = orchestrator.create(total_minutes=max(5.0, min(120.0, minutes)))
    return {"session_id": s.id, "state": s.state.value, "total_minutes": s.total_minutes}


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
    s.total_minutes = max(5.0, min(120.0, minutes))
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
    hits = store.search(question, k=4)
    ctx = "\n\n".join(f"(p{c.page}) {c.text}" for c, _ in hits)
    text = await llm.json_call(
        "Answer the student's question using ONLY the context. Spoken prose, 3-5 sentences.",
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
    audio = await speech.synthesize(ans)
    s = orchestrator.get(sid)
    await s.emit("answer", question=question, answer=ans, audio=audio,
                 citations=[{"page": c.page, "section": c.section} for c, _ in hits])
    return {"answer": ans, "audio": audio}


@router.post("/sessions/{sid}/transcribe")
async def transcribe(sid: str, file: UploadFile = File(...)):
    text = await speech.transcribe(await file.read(), file.content_type or "audio/webm")
    return {"transcript": text}


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

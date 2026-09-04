"""Avatar layer.

Tiered strategy, chosen automatically:
  1. HeyGen streaming avatar (real talking-head video over WebRTC) when a key exists.
  2. LivePortrait/SadTalker worker via AVATAR_WORKER_URL, if deployed.
  3. Local viseme-driven canvas avatar: the frontend animates a rigged SVG head
     from the viseme track. Zero cost, zero latency, always works on stage.

The frontend consumes one uniform contract regardless of tier.
"""
from __future__ import annotations

import os

import httpx

from app.core.config import settings

WORKER_URL = os.getenv("AVATAR_WORKER_URL")


class AvatarService:
    @property
    def mode(self) -> str:
        if settings.heygen_api_key:
            return "heygen"
        if WORKER_URL:
            return "liveportrait"
        return "canvas"

    async def frame_source(self, audio_url: str | None, text: str) -> dict:
        """Return what the client should render for this utterance."""
        if self.mode == "heygen" and audio_url:
            try:
                async with httpx.AsyncClient(timeout=120) as c:
                    r = await c.post(
                        "https://api.heygen.com/v2/video/generate",
                        headers={"X-Api-Key": settings.heygen_api_key or ""},
                        json={
                            "video_inputs": [
                                {
                                    "character": {"type": "avatar",
                                                  "avatar_id": os.getenv("HEYGEN_AVATAR_ID", "")},
                                    "voice": {"type": "text", "input_text": text[:1500]},
                                }
                            ],
                            "dimension": {"width": 720, "height": 720},
                        },
                    )
                    r.raise_for_status()
                    return {"mode": "video", "video_id": r.json()["data"]["video_id"]}
            except Exception:
                pass
        if self.mode == "liveportrait" and audio_url:
            try:
                async with httpx.AsyncClient(timeout=180) as c:
                    r = await c.post(f"{WORKER_URL}/animate", json={"audio_url": audio_url})
                    r.raise_for_status()
                    return {"mode": "video", "video_url": r.json()["video_url"]}
            except Exception:
                pass
        return {"mode": "canvas", "idle": settings.avatar_idle_clip}


avatar = AvatarService()

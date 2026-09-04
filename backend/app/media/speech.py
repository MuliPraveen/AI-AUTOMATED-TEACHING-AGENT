"""Audio pipeline: ElevenLabs TTS + Deepgram STT, with viseme/word timing.

If no key is configured we still emit a full timing track (estimated from
syllable counts) so the frontend's caption highlighting, canvas cue points and
avatar mouth animation work identically in offline demo mode.
"""
from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

import httpx

from app.core.config import settings

AUDIO_DIR = Path(settings.data_dir) / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

_VOWELS = re.compile(r"[aeiouy]+", re.I)


def _syllables(word: str) -> int:
    return max(1, len(_VOWELS.findall(word)))


def estimate_timings(text: str, wpm: int | None = None, language: str = "en") -> list[dict]:
    """Word-level (start, end) seconds — syllable-weighted, punctuation-aware.
    Non-Latin scripts speak slower per word, so the rate is language-dependent."""
    if wpm is None:
        from app.core import i18n

        wpm = i18n.wpm_for(language)
    base = 60.0 / wpm
    out, t = [], 0.0
    cursor = 0
    for w in text.split():
        i = text.find(w, cursor)
        cursor = i + len(w)
        dur = base * (0.55 + 0.45 * _syllables(w))
        out.append({"word": w, "start": round(t, 3), "end": round(t + dur, 3), "char": i})
        t += dur
        if w.endswith((".", "!", "?")):
            t += 0.32
        elif w.endswith((",", ";", ":")):
            t += 0.16
    return out


def duration_of(timings: list[dict]) -> float:
    return round(timings[-1]["end"], 3) if timings else 0.0


def visemes(timings: list[dict]) -> list[dict]:
    """Coarse viseme track driving the avatar's mouth when no video API is used."""
    shapes = ["AI", "E", "O", "U", "MBP", "FV", "L", "rest"]
    out = []
    for w in timings:
        n = max(1, _syllables(w["word"]))
        span = (w["end"] - w["start"]) / n
        for k in range(n):
            out.append(
                {
                    "t": round(w["start"] + k * span, 3),
                    "shape": shapes[(hash(w["word"]) + k) % (len(shapes) - 1)],
                }
            )
        out.append({"t": round(w["end"], 3), "shape": "rest"})
    return out


class SpeechService:
    # ------------------------------------------------------------- TTS --- #
    async def synthesize(self, text: str, language: str = "en") -> dict:
        timings = estimate_timings(text, language=language)
        result = {
            "audio_url": None,
            "timings": timings,
            "visemes": visemes(timings),
            "duration": duration_of(timings),
            "engine": "estimated",
            "language": language,
        }
        if not settings.tts_enabled:
            return result
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/"
                    f"{settings.elevenlabs_voice_id}",
                    headers={
                        "xi-api-key": settings.elevenlabs_api_key or "",
                        "accept": "audio/mpeg",
                    },
                    json={
                        "text": text,
                        # multilingual model: one voice speaks all supported languages
                        "model_id": "eleven_turbo_v2_5",
                        "language_code": language.split("-")[0],
                        "voice_settings": {
                            "stability": 0.45,
                            "similarity_boost": 0.75,
                            "style": 0.3,
                            "use_speaker_boost": True,
                        },
                    },
                )
                r.raise_for_status()
                name = f"{uuid.uuid4().hex[:12]}.mp3"
                (AUDIO_DIR / name).write_bytes(r.content)
                result["audio_url"] = f"/media/audio/{name}"
                result["engine"] = "elevenlabs"
        except Exception as e:  # graceful degradation — the lesson still runs
            result["error"] = f"tts_failed: {type(e).__name__}"
        return result

    # ------------------------------------------------------------- STT --- #
    async def transcribe(
        self, audio: bytes, mimetype: str = "audio/webm", language: str = "en"
    ) -> str:
        if not settings.stt_enabled:
            return ""
        lang = language.split("-")[0]
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(
                    "https://api.deepgram.com/v1/listen"
                    f"?model=nova-2&smart_format=true&punctuate=true&language={lang}",
                    headers={
                        "Authorization": f"Token {settings.deepgram_api_key}",
                        "Content-Type": mimetype,
                    },
                    content=audio,
                )
                r.raise_for_status()
                return (
                    r.json()["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
                )
        except Exception:
            return ""


speech = SpeechService()

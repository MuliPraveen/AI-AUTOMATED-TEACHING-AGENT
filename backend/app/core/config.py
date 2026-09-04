"""Central configuration. Every external dependency is optional:
the platform detects available keys at boot and selects the best provider,
falling back to deterministic local implementations otherwise."""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "AI Automated Teaching Agent"
    version: str = "1.0.0"

    # --- LLM ---
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")

    # --- Speech ---
    elevenlabs_api_key: str | None = os.getenv("ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
    deepgram_api_key: str | None = os.getenv("DEEPGRAM_API_KEY")

    # --- Avatar ---
    heygen_api_key: str | None = os.getenv("HEYGEN_API_KEY")
    avatar_idle_clip: str = os.getenv("AVATAR_IDLE_CLIP", "/static/avatar/idle.mp4")

    # --- Storage ---
    data_dir: str = os.getenv("DATA_DIR", "./data")
    chroma_dir: str = os.getenv("CHROMA_DIR", "./data/chroma")

    # --- Pedagogy defaults ---
    default_session_minutes: int = 20
    words_per_minute: int = 140

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key or self.anthropic_api_key)

    @property
    def tts_enabled(self) -> bool:
        return bool(self.elevenlabs_api_key)

    @property
    def stt_enabled(self) -> bool:
        return bool(self.deepgram_api_key)

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    os.makedirs(s.data_dir, exist_ok=True)
    return s


settings = get_settings()

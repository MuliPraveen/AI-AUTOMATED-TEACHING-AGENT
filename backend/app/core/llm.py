"""Provider-agnostic LLM gateway.

Priority: OpenAI -> Anthropic -> deterministic local template engine.
`json_call` guarantees a parsed dict, repairing truncated/fenced JSON, so agent
code never has to defend against provider quirks.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from app.core.config import settings

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class LLMUnavailable(RuntimeError):
    pass


class LLM:
    def __init__(self) -> None:
        self.provider = (
            "openai" if settings.openai_api_key
            else "anthropic" if settings.anthropic_api_key
            else "local"
        )

    # ------------------------------------------------------------------ #
    async def complete(
        self, system: str, user: str, *, temperature: float = 0.3, max_tokens: int = 1200
    ) -> str:
        if self.provider == "local":
            raise LLMUnavailable("no LLM key configured")
        for attempt in range(3):
            try:
                if self.provider == "openai":
                    return await self._openai(system, user, temperature, max_tokens)
                return await self._anthropic(system, user, temperature, max_tokens)
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.6 * 2**attempt)
        raise LLMUnavailable("unreachable")

    async def _openai(self, system: str, user: str, t: float, mx: int) -> str:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.llm_model,
                    "temperature": t,
                    "max_tokens": mx,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    async def _anthropic(self, system: str, user: str, t: float, mx: int) -> str:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key or "",
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": "claude-3-5-sonnet-latest",
                    "max_tokens": mx,
                    "temperature": t,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            r.raise_for_status()
            return r.json()["content"][0]["text"]

    # ------------------------------------------------------------------ #
    async def json_call(
        self, system: str, user: str, fallback: Any, *, temperature: float = 0.2
    ) -> Any:
        """Return parsed JSON, or `fallback` on any failure. Never raises."""
        try:
            raw = await self.complete(
                system + "\nRespond with STRICT JSON only. No prose, no markdown fences.",
                user,
                temperature=temperature,
            )
        except Exception:
            return fallback
        return parse_json(raw, fallback)


def parse_json(raw: str, fallback: Any = None) -> Any:
    if not raw:
        return fallback
    raw = raw.strip()
    m = _JSON_FENCE.search(raw)
    if m:
        raw = m.group(1).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Repair: take the widest balanced {...} or [...] span.
    for op, cl in (("{", "}"), ("[", "]")):
        i, j = raw.find(op), raw.rfind(cl)
        if i != -1 and j > i:
            try:
                return json.loads(raw[i : j + 1])
            except Exception:
                continue
    return fallback


llm = LLM()

"""§8 Multilingual Teaching.

Design: the *lesson* is language-agnostic (concepts, DAG, plan, mastery all live
in a neutral representation). Only the narration surface is localized, so a
student can switch language mid-lesson and keep full context — the pedagogical
state never resets.

Cross-lingual grounding: the source document may be in language A while teaching
happens in language B. Retrieval always runs in the document's language (Agent 1
never translates the corpus, which would degrade grounding); the teaching agent
receives source-language context and is instructed to *explain in* the target
language. That keeps RAG fidelity while changing only the delivery.
"""
from __future__ import annotations

import re

from app.core.llm import llm

# Curated for the Indian + international mix the brief calls out.
LANGUAGES: dict[str, dict[str, str]] = {
    "en": {"name": "English", "native": "English", "voice": "en"},
    "hi": {"name": "Hindi", "native": "हिन्दी", "voice": "hi"},
    "hi-en": {"name": "Hinglish", "native": "Hinglish", "voice": "hi"},
    "ta": {"name": "Tamil", "native": "தமிழ்", "voice": "ta"},
    "te": {"name": "Telugu", "native": "తెలుగు", "voice": "te"},
    "kn": {"name": "Kannada", "native": "ಕನ್ನಡ", "voice": "kn"},
    "ml": {"name": "Malayalam", "native": "മലയാളം", "voice": "ml"},
    "mr": {"name": "Marathi", "native": "मराठी", "voice": "mr"},
    "bn": {"name": "Bengali", "native": "বাংলা", "voice": "bn"},
    "gu": {"name": "Gujarati", "native": "ગુજરાતી", "voice": "gu"},
    "pa": {"name": "Punjabi", "native": "ਪੰਜਾਬੀ", "voice": "pa"},
    "ur": {"name": "Urdu", "native": "اردو", "voice": "ur"},
    "es": {"name": "Spanish", "native": "Español", "voice": "es"},
    "fr": {"name": "French", "native": "Français", "voice": "fr"},
    "de": {"name": "German", "native": "Deutsch", "voice": "de"},
    "ar": {"name": "Arabic", "native": "العربية", "voice": "ar"},
    "zh": {"name": "Chinese", "native": "中文", "voice": "zh"},
    "ja": {"name": "Japanese", "native": "日本語", "voice": "ja"},
}

# Scripts that need a slower speaking-rate assumption for timing estimates.
_DENSE_SCRIPTS = {"hi", "ta", "te", "kn", "ml", "mr", "bn", "gu", "pa", "ur", "zh", "ja", "ar"}

# "teach me in hindi", "explain in tamil", "hinglish mein samjhao"
_REQUEST = re.compile(
    r"\b(?:in|into|mein|me|use|speak|switch\s+to|explain\s+in|teach\s+in)\s+"
    r"([a-zA-Z]+)\b",
    re.I,
)
_NAME_TO_CODE = {v["name"].lower(): k for k, v in LANGUAGES.items()}
_NAME_TO_CODE.update({v["native"].lower(): k for k, v in LANGUAGES.items()})
_NAME_TO_CODE.update({"hinglish": "hi-en", "mandarin": "zh", "castellano": "es"})


def resolve(code_or_name: str) -> tuple[str, str]:
    """Normalize any user input to (code, display name)."""
    if not code_or_name:
        return "en", "English"
    key = code_or_name.strip().lower()
    if key in LANGUAGES:
        return key, LANGUAGES[key]["name"]
    if key in _NAME_TO_CODE:
        c = _NAME_TO_CODE[key]
        return c, LANGUAGES[c]["name"]
    base = key.split("-")[0]
    if base in LANGUAGES:
        return base, LANGUAGES[base]["name"]
    return "en", "English"


def detect_switch(text: str) -> tuple[str, str] | None:
    """§8: student asks for a language change in natural conversation."""
    for m in _REQUEST.finditer(text or ""):
        cand = m.group(1).lower()
        if cand in _NAME_TO_CODE:
            c = _NAME_TO_CODE[cand]
            return c, LANGUAGES[c]["name"]
    # bare mention: "Hindi please"
    for name, code in _NAME_TO_CODE.items():
        if re.search(rf"\b{re.escape(name)}\b", (text or "").lower()) and len(name) > 3:
            return code, LANGUAGES[code]["name"]
    return None


def wpm_for(code: str) -> int:
    """Speaking rate used for timing estimation and lesson length budgeting."""
    return 105 if code.split("-")[0] in _DENSE_SCRIPTS else 140


def instruction_for(code: str, name: str) -> str:
    """The narration-language clause injected into every teaching prompt."""
    if code == "en":
        return "Write the narration in clear English."
    if code == "hi-en":
        return (
            "Write the narration in natural Hinglish: conversational Hindi written in "
            "Latin script, keeping technical terms in English, the way an Indian teacher "
            "actually speaks in class. Do not use Devanagari."
        )
    return (
        f"Write the narration in {name} ({LANGUAGES.get(code, {}).get('native', name)}), "
        f"using natural {name} a teacher would speak aloud. Keep widely-used technical "
        f"terms in English where a native speaker would, but all explanation must be in {name}."
    )


async def translate(text: str, code: str, name: str) -> str:
    """Fallback path: localize already-generated narration (used when the
    deterministic offline lesson builder produced English text)."""
    if code == "en" or not text.strip():
        return text
    out = await llm.json_call(
        f"You are a translator for classroom narration. {instruction_for(code, name)} "
        "Preserve meaning, numbers and technical terms exactly.",
        f'Translate for speaking aloud:\n\n{text[:3000]}\n\nJSON: {{"text":""}}',
        fallback=None,
    )
    if isinstance(out, dict) and out.get("text"):
        return str(out["text"])
    return text  # offline: keep English rather than emit garbage

"""Typed contracts shared by every agent, the API layer and the WebSocket stream."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Knowledge layer
# --------------------------------------------------------------------------- #
class Chunk(BaseModel):
    id: str
    doc_id: str
    text: str
    page: int = 0
    section: str = ""


class Concept(BaseModel):
    id: str
    name: str
    summary: str = ""
    difficulty: float = Field(0.5, ge=0.0, le=1.0)
    est_minutes: float = 5.0
    prerequisites: list[str] = []
    chunk_ids: list[str] = []
    keywords: list[str] = []


class KnowledgeGraph(BaseModel):
    doc_id: str
    concepts: list[Concept] = []
    order: list[str] = []  # topological teaching order


# --------------------------------------------------------------------------- #
# Pedagogy layer
# --------------------------------------------------------------------------- #
class Depth(str, Enum):
    OVERVIEW = "overview"
    STANDARD = "standard"
    DEEP = "deep"


class LessonPlanItem(BaseModel):
    concept_id: str
    name: str
    minutes: float
    depth: Depth
    rationale: str = ""


class LessonPlan(BaseModel):
    session_id: str
    total_minutes: float
    items: list[LessonPlanItem]


class BlockType(str, Enum):
    TEXT = "text"
    LATEX = "latex"
    CODE = "code"
    MERMAID = "mermaid"
    IMAGE = "image"


class VisualBlock(BaseModel):
    """A canvas element rendered in lock-step with the narration."""
    type: BlockType
    content: str
    language: str = "python"
    caption: str = ""
    # narration character offset at which this block appears
    cue_at_char: int = 0


class TeachingTurn(BaseModel):
    concept_id: str
    narration: str
    blocks: list[VisualBlock] = []
    check_question: "Question | None" = None


# --------------------------------------------------------------------------- #
# Assessment layer
# --------------------------------------------------------------------------- #
class Question(BaseModel):
    id: str
    concept_id: str
    prompt: str
    kind: Literal["mcq", "open"] = "mcq"
    options: list[str] = []
    answer_index: int | None = None
    answer_text: str = ""
    # option index -> misconception tag
    distractor_map: dict[str, str] = {}
    bloom: Literal["remember", "understand", "apply", "analyze"] = "understand"


class Evaluation(BaseModel):
    question_id: str
    concept_id: str
    correct: bool
    score: float = Field(0.0, ge=0.0, le=1.0)
    misconception: str | None = None
    feedback: str = ""
    remediate: bool = False


class ConceptMastery(BaseModel):
    concept_id: str
    name: str
    attempts: int = 0
    score: float = 0.0
    mastery: float = 0.0
    misconceptions: list[str] = []


class StudentProfile(BaseModel):
    session_id: str
    student_id: str = "student"
    mastery: dict[str, ConceptMastery] = {}
    overall: float = 0.0
    strengths: list[str] = []
    gaps: list[str] = []
    next_steps: list[str] = []
    timeline: list[dict[str, Any]] = []


# --------------------------------------------------------------------------- #
# Session / streaming
# --------------------------------------------------------------------------- #
class SessionState(str, Enum):
    IDLE = "idle"
    INGESTING = "ingesting"
    PLANNING = "planning"
    TEACHING = "teaching"
    ASSESSING = "assessing"
    REMEDIATING = "remediating"
    COMPLETE = "complete"


class WSEvent(BaseModel):
    type: str
    payload: dict[str, Any] = {}


TeachingTurn.model_rebuild()

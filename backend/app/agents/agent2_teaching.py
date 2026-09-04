"""AGENT 2 — Teaching & Pedagogical agent.

Two jobs:
  * `plan()`  — time/depth allocation across the concept DAG under a hard time
                budget, weighted by difficulty, prerequisite centrality and the
                live student mastery profile (adaptive re-planning).
  * `teach()` — produce one narration turn plus synchronized visual blocks
                (LaTeX / code / Mermaid) with character-level cue points so the
                canvas reveals in lock-step with the TTS audio.
"""
from __future__ import annotations

import re

from app.core import i18n
from app.core.config import settings
from app.core.llm import llm
from app.core.schemas import (
    BlockType,
    Concept,
    Depth,
    KnowledgeGraph,
    LearnerProfile,
    LessonPlan,
    LessonPlanItem,
    Level,
    Question,
    StudentProfile,
    TeachingTurn,
    VisualBlock,
)
from app.ingest.vector_store import store

SYSTEM_TEACH = """You are an expert human teacher delivering a live spoken lesson.
Rules:
- Narration is SPOKEN prose: no markdown, no bullet symbols, no LaTeX in narration.
- Teach like a real classroom teacher: hook the student, give a concrete example or
  analogy BEFORE the formal definition, then check understanding.
- Ground every claim in the provided context; never invent facts beyond it.
- cue_at_char = the narration character offset where the visual should appear.
- End with one check-for-understanding question whose wrong options encode real,
  specific misconceptions a student of this level would actually hold."""

# §6 Personalized Teaching — level drives terminology, examples and rigor.
LEVEL_STYLE: dict[Level, str] = {
    Level.BEGINNER: (
        "Learner is a BEGINNER. Use everyday language and familiar analogies. Define every "
        "technical term the moment you use it. Prefer intuition over formalism; use at most "
        "one simple formula. Be encouraging and concrete."
    ),
    Level.INTERMEDIATE: (
        "Learner is INTERMEDIATE. Assume the basics are known. Use correct technical "
        "terminology, give practical worked examples, and show the reasoning steps."
    ),
    Level.ADVANCED: (
        "Learner is ADVANCED. Use precise technical terminology, include the mathematics or "
        "implementation details, discuss edge cases, trade-offs and why naive approaches fail."
    ),
}

# §10 Subject-Aware Visual Explanation — each subject gets its own visual grammar.
SUBJECT_VISUALS: dict[str, str] = {
    "mathematics": "Use latex blocks for equations and step-by-step derivations; a mermaid "
                   "block for solution procedure. Show each algebraic step separately.",
    "physics": "Use latex for formulas and mermaid for force/circuit/process diagrams. "
               "Always state units and the physical intuition behind each symbol.",
    "chemistry": "Use latex for balanced equations and mermaid for reaction pathways and "
                 "mechanisms.",
    "biology": "Use mermaid flowcharts for biological processes and labeled structures; "
               "describe diagrams the student should picture.",
    "history": "Use a mermaid timeline or graph of causes and consequences; anchor every "
               "event to a date.",
    "programming": "Use runnable code blocks with the correct language tag, plus a mermaid "
                   "block for execution flow or architecture. Show expected output.",
    "economics": "Use latex for formulas and mermaid for supply/demand or flow relationships.",
    "general": "Use a mermaid diagram to structure the idea; add latex or code only if the "
               "material genuinely calls for it.",
}


def _depth_for(minutes: float) -> Depth:
    if minutes < 3.5:
        return Depth.OVERVIEW
    if minutes < 8:
        return Depth.STANDARD
    return Depth.DEEP


class TeachingAgent:
    # ------------------------------------------------------------- plan --- #
    def plan(
        self,
        session_id: str,
        kg: KnowledgeGraph,
        total_minutes: float | None = None,
        profile: StudentProfile | None = None,
    ) -> LessonPlan:
        budget = float(total_minutes or settings.default_session_minutes)
        by_id = {c.id: c for c in kg.concepts}
        # Prerequisite centrality: how many concepts transitively depend on this one.
        dependents: dict[str, int] = {c.id: 0 for c in kg.concepts}
        for c in kg.concepts:
            for p in c.prerequisites:
                if p in dependents:
                    dependents[p] += 1

        weights: dict[str, float] = {}
        for cid in kg.order:
            c = by_id[cid]
            w = 0.6 + 0.9 * c.difficulty + 0.25 * dependents.get(cid, 0)
            if profile and (m := profile.mastery.get(cid)):
                # Spend more time where the student is demonstrably weak.
                w *= 1.0 + 1.2 * (1.0 - m.mastery)
            weights[cid] = w

        total_w = sum(weights.values()) or 1.0
        items: list[LessonPlanItem] = []
        for cid in kg.order:
            c = by_id[cid]
            raw = budget * weights[cid] / total_w
            minutes = round(max(2.0, min(c.est_minutes * 1.5, raw)), 1)
            depth = _depth_for(minutes)
            items.append(
                LessonPlanItem(
                    concept_id=cid,
                    name=c.name,
                    minutes=minutes,
                    depth=depth,
                    rationale=(
                        f"difficulty {c.difficulty:.2f}, {dependents.get(cid,0)} dependent "
                        f"concept(s)" + (", weak mastery -> extra time" if profile and
                        cid in profile.mastery and profile.mastery[cid].mastery < 0.6 else "")
                    ),
                )
            )
        # Renormalize to respect the hard budget exactly.
        scale = budget / max(sum(i.minutes for i in items), 1e-6)
        for i in items:
            i.minutes = round(i.minutes * scale, 1)
            i.depth = _depth_for(i.minutes)
        return LessonPlan(session_id=session_id, total_minutes=budget, items=items)

    # ------------------------------------------------------------ teach --- #
    async def teach(
        self,
        concept: Concept,
        item: LessonPlanItem,
        *,
        remediation: str | None = None,
        learner: LearnerProfile | None = None,
        subject: str = "general",
        attempt: int = 0,
    ) -> TeachingTurn:
        learner = learner or LearnerProfile()
        context = self._context_for(concept)
        wpm = i18n.wpm_for(learner.language)
        words = int(item.minutes * wpm)

        # §12: on re-explanation, force a *different* analogy rather than a repeat.
        remediation_clause = ""
        if remediation:
            remediation_clause = (
                f"RE-EXPLANATION (attempt {attempt + 1}). The student answered incorrectly and "
                f"appears to hold this misconception: '{remediation}'. Do NOT repeat your "
                f"previous explanation. Name the misconception explicitly, show with a "
                f"counter-example why it fails, then re-teach using a COMPLETELY DIFFERENT "
                f"analogy from a different domain. Finish with a new, easier question.\n"
            )

        instruction = (
            f"Concept: {concept.name}\nSubject: {subject}\nDepth: {item.depth.value}\n"
            f"{LEVEL_STYLE[learner.level]}\n"
            f"{i18n.instruction_for(learner.language, learner.language_name)}\n"
            f"VISUALS: {SUBJECT_VISUALS.get(subject, SUBJECT_VISUALS['general'])}\n"
            + (f"Learning objective: {learner.objective}\n" if learner.objective else "")
            + (f"Preferred style: {learner.style}\n" if learner.style else "")
            + f"Narration length: about {words} words.\n"
            + remediation_clause
            + f"\nCONTEXT (may be in a different language — explain it in "
              f"{learner.language_name}):\n{context}\n\n"
            'JSON schema: {"narration":"","blocks":[{"type":"latex|code|mermaid|text",'
            '"content":"","language":"python","caption":"","cue_at_char":0}],'
            '"check_question":{"prompt":"","kind":"mcq","options":["","","",""],'
            '"answer_index":0,"distractor_map":{"1":"misconception tag","2":"...","3":"..."},'
            '"bloom":"understand"}}'
        )
        data = await llm.json_call(
            SYSTEM_TEACH, instruction, fallback=None, temperature=0.45 + 0.15 * attempt
        )
        if not isinstance(data, dict) or not data.get("narration"):
            return await self._fallback_turn(concept, item, context, remediation, learner,
                                             subject)
        narration = self._sanitize(str(data["narration"]))
        blocks = self._blocks_from(data.get("blocks", []), len(narration))
        q = self._question_from(data.get("check_question"), concept)
        return TeachingTurn(concept_id=concept.id, narration=narration, blocks=blocks,
                            check_question=q)

    # ---------------------------------------------------------- helpers --- #
    def _context_for(self, concept: Concept, budget_chars: int = 4000) -> str:
        chunks = store.by_ids(concept.chunk_ids)
        if len(chunks) < 3:
            chunks += [c for c, _ in store.search(
                f"{concept.name} {' '.join(concept.keywords)}", k=4)]
        seen, out, used = set(), [], 0
        for c in chunks:
            if c.id in seen:
                continue
            seen.add(c.id)
            piece = f"(p{c.page}) {c.text}"
            if used + len(piece) > budget_chars:
                break
            out.append(piece)
            used += len(piece)
        return "\n\n".join(out) or concept.summary

    @staticmethod
    def _sanitize(text: str) -> str:
        """Strip markdown artifacts so TTS never reads asterisks or hashes aloud."""
        text = re.sub(r"[*_`#]+", "", text)
        text = re.sub(r"\$\$?(.*?)\$\$?", r"\1", text, flags=re.S)
        text = re.sub(r"\(p\d+\)\s*", "", text)  # drop page citations from spoken audio
        return re.sub(r"\s{2,}", " ", text).strip()

    @staticmethod
    def _blocks_from(raw: list, narration_len: int) -> list[VisualBlock]:
        blocks: list[VisualBlock] = []
        for b in raw[:6]:
            try:
                t = BlockType(str(b.get("type", "text")).lower())
            except ValueError:
                t = BlockType.TEXT
            content = str(b.get("content", "")).strip()
            if not content:
                continue
            blocks.append(
                VisualBlock(
                    type=t,
                    content=content,
                    language=str(b.get("language", "python")),
                    caption=str(b.get("caption", ""))[:120],
                    cue_at_char=max(0, min(narration_len, int(b.get("cue_at_char", 0) or 0))),
                )
            )
        # Guarantee monotonically increasing, well-spread cues.
        if blocks:
            span = max(narration_len, 1)
            for i, b in enumerate(blocks):
                floor = int(span * (i + 0.5) / (len(blocks) + 1))
                b.cue_at_char = max(b.cue_at_char, floor if b.cue_at_char == 0 else b.cue_at_char)
            for prev, cur in zip(blocks, blocks[1:]):
                cur.cue_at_char = max(cur.cue_at_char, prev.cue_at_char + 20)
        return blocks

    @staticmethod
    def _question_from(raw, concept: Concept) -> Question | None:
        if not isinstance(raw, dict) or not raw.get("prompt"):
            return None
        opts = [str(o) for o in raw.get("options", [])][:4]
        if len(opts) < 2:
            return None
        return Question(
            id=f"{concept.id}-q{abs(hash(raw['prompt'])) % 9999}",
            concept_id=concept.id,
            prompt=str(raw["prompt"]),
            kind="mcq",
            options=opts,
            answer_index=int(raw.get("answer_index", 0)) % len(opts),
            distractor_map={str(k): str(v) for k, v in (raw.get("distractor_map") or {}).items()},
            bloom=str(raw.get("bloom", "understand")),  # type: ignore[arg-type]
        )

    async def _fallback_turn(
        self,
        concept: Concept,
        item: LessonPlanItem,
        context: str,
        remediation: str | None,
        learner: LearnerProfile,
        subject: str = "general",
    ) -> TeachingTurn:
        """Deterministic, source-grounded lesson used when no LLM key is present.
        It extracts real sentences from the document so the demo is never empty."""
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", context) if len(s.strip()) > 40]
        budget = int(item.minutes * i18n.wpm_for(learner.language))
        body, count = [], 0
        for s in sents:
            body.append(s)
            count += len(s.split())
            if count >= budget:
                break
        opener = (
            f"Let's clear up a common misunderstanding about {concept.name}. "
            if remediation
            else f"Now let's work through {concept.name}. "
        )
        narration = self._sanitize(
            opener
            + " ".join(body)
            + f" To summarize, {concept.name} matters because it underpins the ideas that follow."
        )
        # §8: localize the offline narration too, when an LLM is reachable.
        narration = await i18n.translate(narration, learner.language, learner.language_name)
        blocks = [self._default_visual(concept, subject, narration)]
        q = Question(
            id=f"{concept.id}-q0",
            concept_id=concept.id,
            prompt=f"Which statement best describes {concept.name}?",
            options=[
                (concept.summary or body[0] if body else concept.name)[:140],
                f"{concept.name} is unrelated to the rest of this material.",
                f"{concept.name} only applies to trivial edge cases.",
                f"{concept.name} is simply another name for its prerequisite.",
            ],
            answer_index=0,
            distractor_map={
                "1": "isolated-concept",
                "2": "scope-underestimation",
                "3": "concept-conflation",
            },
        )
        return TeachingTurn(concept_id=concept.id, narration=narration, blocks=blocks,
                            check_question=q)

    @staticmethod
    def _default_visual(concept: Concept, subject: str, narration: str) -> VisualBlock:
        """§10 offline path: pick the visual grammar that fits the subject."""
        safe = re.sub(r"[\[\]()\"']", "", concept.name)[:30]
        cue = min(120, max(20, len(narration) // 4))
        if subject == "programming":
            return VisualBlock(
                type=BlockType.CODE,
                content=f"# {safe}\ndef demo():\n    \"\"\"{concept.summary[:70]}\"\"\"\n"
                        f"    result = ...  # apply {safe}\n    return result",
                language="python", caption=f"{concept.name} in code", cue_at_char=cue,
            )
        if subject == "history":
            return VisualBlock(
                type=BlockType.MERMAID,
                content=f"graph LR\n  A[Causes] --> B[{safe}] --> C[Consequences]",
                caption=f"{concept.name}: causes and consequences", cue_at_char=cue,
            )
        if subject in ("mathematics", "physics", "economics"):
            return VisualBlock(
                type=BlockType.MERMAID,
                content=f"graph TD\n  A[Given] --> B[Apply {safe}] --> C[Result]",
                caption=f"{concept.name}: solution procedure", cue_at_char=cue,
            )
        return VisualBlock(
            type=BlockType.MERMAID,
            content=f"graph LR\n  A[Input] --> B[{safe}] --> C[Outcome]",
            caption=f"{concept.name} at a glance", cue_at_char=cue,
        )


teaching_agent = TeachingAgent()

"""AGENT 3 — Assessment & Misconception diagnosis.

Grades MCQ answers deterministically (zero latency, zero cost) and open answers
semantically. Every wrong answer is mapped to a *named misconception* which is
fed back into Agent 2 for targeted remediation, and into the mastery model.

Mastery uses an exponentially-weighted Bayesian-ish update:
    m <- m + alpha * (score - m),  alpha decaying with attempts,
which converges fast yet resists a single lucky guess.
"""
from __future__ import annotations

import re

from app.core.llm import llm
from app.core.schemas import (
    ConceptMastery,
    Evaluation,
    KnowledgeGraph,
    Question,
    StudentProfile,
)
from app.ingest.vector_store import tokenize

SYSTEM_EVAL = (
    "You are a strict but supportive examiner. Grade the student's answer against the "
    "reference. Identify the specific misconception if wrong. Feedback is 1-2 sentences, "
    "addressed to the student, and must state the correct idea."
)
MASTERY_PASS = 0.7


class AssessmentAgent:
    # --------------------------------------------------------------- eval --
    async def evaluate(self, q: Question, answer: str | int) -> Evaluation:
        if q.kind == "mcq":
            return self._grade_mcq(q, answer)
        return await self._grade_open(q, str(answer))

    def _grade_mcq(self, q: Question, answer: str | int) -> Evaluation:
        try:
            idx = int(answer)
        except (TypeError, ValueError):
            idx = next(
                (i for i, o in enumerate(q.options)
                 if o.strip().lower() == str(answer).strip().lower()), -1
            )
        correct = idx == q.answer_index
        mis = None if correct else q.distractor_map.get(str(idx))
        right = q.options[q.answer_index] if q.answer_index is not None else ""
        return Evaluation(
            question_id=q.id,
            concept_id=q.concept_id,
            correct=correct,
            score=1.0 if correct else 0.0,
            misconception=mis,
            feedback=(
                "Exactly right — that's the key idea."
                if correct
                else f"Not quite. The correct answer is: {right}."
                + (f" You appear to be assuming '{mis.replace('-', ' ')}'." if mis else "")
            ),
            remediate=not correct,
        )

    async def _grade_open(self, q: Question, answer: str) -> Evaluation:
        # Lexical overlap gives an instant, dependency-free baseline score.
        ref, got = set(tokenize(q.answer_text)), set(tokenize(answer))
        overlap = len(ref & got) / max(len(ref), 1) if ref else 0.0
        data = await llm.json_call(
            SYSTEM_EVAL,
            f"Question: {q.prompt}\nReference: {q.answer_text}\nStudent: {answer}\n"
            'JSON: {"score":0..1,"misconception":null|"tag","feedback":""}',
            fallback=None,
        )
        if isinstance(data, dict) and "score" in data:
            score = max(0.0, min(1.0, float(data.get("score", overlap))))
            mis = data.get("misconception") or None
            fb = str(data.get("feedback", ""))
        else:
            score, mis = overlap, (None if overlap >= MASTERY_PASS else "incomplete-explanation")
            fb = (
                "Good — you covered the key points."
                if overlap >= MASTERY_PASS
                else f"Partially correct. Make sure you mention: {q.answer_text[:160]}"
            )
        return Evaluation(
            question_id=q.id,
            concept_id=q.concept_id,
            correct=score >= MASTERY_PASS,
            score=score,
            misconception=str(mis) if mis else None,
            feedback=fb,
            remediate=score < MASTERY_PASS,
        )

    # ------------------------------------------------------------ profile --
    @staticmethod
    def update_profile(
        profile: StudentProfile, kg: KnowledgeGraph, ev: Evaluation, concept_name: str
    ) -> StudentProfile:
        m = profile.mastery.get(ev.concept_id) or ConceptMastery(
            concept_id=ev.concept_id, name=concept_name
        )
        m.attempts += 1
        alpha = 1.0 / (1.0 + 0.7 * (m.attempts - 1))  # decaying learning rate
        m.mastery = round(m.mastery + alpha * (ev.score - m.mastery), 3)
        m.score = round((m.score * (m.attempts - 1) + ev.score) / m.attempts, 3)
        if ev.misconception and ev.misconception not in m.misconceptions:
            m.misconceptions.append(ev.misconception)
        profile.mastery[ev.concept_id] = m

        vals = [x.mastery for x in profile.mastery.values()]
        profile.overall = round(sum(vals) / len(vals), 3) if vals else 0.0
        profile.strengths = [x.name for x in profile.mastery.values() if x.mastery >= 0.8]
        profile.gaps = [x.name for x in profile.mastery.values() if x.mastery < MASTERY_PASS]
        profile.next_steps = AssessmentAgent._next_steps(profile, kg)
        profile.timeline.append(
            {
                "concept_id": ev.concept_id,
                "concept": concept_name,
                "score": ev.score,
                "misconception": ev.misconception,
            }
        )
        return profile

    @staticmethod
    def _next_steps(profile: StudentProfile, kg: KnowledgeGraph) -> list[str]:
        """Learning-path suggestions: a gap is only actionable once its
        prerequisites are mastered — otherwise recommend the prerequisite first."""
        by_id = {c.id: c for c in kg.concepts}
        steps: list[str] = []
        for cid, m in sorted(profile.mastery.items(), key=lambda kv: kv[1].mastery):
            if m.mastery >= MASTERY_PASS:
                continue
            c = by_id.get(cid)
            if not c:
                continue
            weak_prereq = next(
                (by_id[p].name for p in c.prerequisites
                 if p in profile.mastery and profile.mastery[p].mastery < MASTERY_PASS
                 and p in by_id),
                None,
            )
            steps.append(
                f"Revisit '{weak_prereq}' before retrying '{c.name}'."
                if weak_prereq
                else f"Practice '{c.name}'"
                + (f" — targeting the '{m.misconceptions[-1].replace('-', ' ')}' misconception."
                   if m.misconceptions else ".")
            )
            if len(steps) >= 5:
                break
        if not steps and profile.mastery:
            steps.append("All concepts mastered — advance to applied problem sets.")
        return steps

    # ----------------------------------------------------------- quizzing --
    async def final_quiz(
        self,
        kg: KnowledgeGraph,
        profile: StudentProfile,
        n: int = 5,
        learner: "LearnerProfile | None" = None,
    ) -> list[Question]:
        """Weighted toward weak concepts (spaced-repetition style selection)."""
        from app.core import i18n
        from app.core.schemas import LearnerProfile

        learner = learner or LearnerProfile()
        ranked = sorted(
            kg.concepts,
            key=lambda c: profile.mastery.get(c.id).mastery if c.id in profile.mastery else 0.0,
        )
        picks = ranked[:n] or kg.concepts[:n]
        out: list[Question] = []
        for c in picks:
            data = await llm.json_call(
                "Write one exam MCQ. Distractors must encode realistic misconceptions. "
                f"Pitch it at a {learner.level.value} learner. "
                + i18n.instruction_for(learner.language, learner.language_name),
                f"Concept: {c.name}\nSummary: {c.summary[:600]}\n"
                'JSON: {"prompt":"","options":["","","",""],"answer_index":0,'
                '"distractor_map":{"1":"tag"},"bloom":"apply"}',
                fallback=None,
            )
            if isinstance(data, dict) and data.get("options"):
                out.append(
                    Question(
                        id=f"final-{c.id}",
                        concept_id=c.id,
                        prompt=str(data["prompt"]),
                        options=[str(o) for o in data["options"]][:4],
                        answer_index=int(data.get("answer_index", 0)),
                        distractor_map={str(k): str(v)
                                        for k, v in (data.get("distractor_map") or {}).items()},
                        bloom=str(data.get("bloom", "apply")),  # type: ignore[arg-type]
                    )
                )
            else:
                out.append(
                    Question(
                        id=f"final-{c.id}",
                        concept_id=c.id,
                        prompt=f"Which is the most accurate statement about {c.name}?",
                        options=[
                            (c.summary or c.name)[:140],
                            f"{c.name} has no prerequisites in this material.",
                            f"{c.name} is only a naming convention.",
                            f"{c.name} contradicts the earlier concepts.",
                        ],
                        answer_index=0,
                        distractor_map={"1": "isolated-concept", "2": "surface-learning",
                                        "3": "concept-conflation"},
                        bloom="apply",
                    )
                )
        return out


assessment_agent = AssessmentAgent()

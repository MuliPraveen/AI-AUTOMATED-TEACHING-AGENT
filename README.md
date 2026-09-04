# AI Teacher — A Human-Like AI Educator That Teaches Through Video

**Round 2 Technical Assessment · AI Innovation Hackathon 2026 · Bharat Academix**

An AI Teacher that takes an uploaded book/PDF/DOCX/PPTX **or a bare topic**, plans a
lesson, teaches it aloud through a talking avatar with subject-appropriate visuals in
**18 languages**, questions the student mid-lesson, diagnoses *specific misconceptions*,
re-explains with a different analogy, and closes with a graded learning report.

> **Runs with zero API keys.** Every external service (LLM, TTS, STT, avatar video) has a
> deterministic local fallback, so the demo never fails on stage. Add keys to upgrade each
> tier in place — no code changes. `GET /api/health` reports which tier is live.

---

## 1. Problem statement

Traditional digital learning gives you pre-recorded lectures or a text chatbot. Neither
*teaches*: they don't plan, don't check whether you understood, don't notice **why** you got
something wrong, and don't adapt. This project builds an AI Teacher that follows the actual
human teaching loop:

```
Understand → Plan → Explain → Demonstrate → Question → Evaluate → Adapt → Continue
```

## 2. Solution overview

Three specialist agents behind an explicit state machine. The key design idea: **the lesson
state is language- and modality-neutral**. Concepts, the prerequisite DAG, the time plan and
the mastery model live in a neutral representation; only the *narration surface* is localized
and voiced. That's why a student can switch from English to Tamil mid-lesson and keep every
bit of progress.

```
┌──────────────────────────────────────────────────────────────┐
│  FRONTEND (Next.js 14 · React 18 · Tailwind)                 │
│  Talking Avatar · Synced Canvas (KaTeX/Mermaid/Code) · Report│
└───────────────┬──────────────────────────┬───────────────────┘
       WebSocket events              Audio / video stream
┌───────────────┴──────────────────────────┴───────────────────┐
│  ORCHESTRATOR (FastAPI · finite state machine)               │
│  IDLE→INGESTING→PLANNING→TEACHING⇄ASSESSING⇄REMEDIATING→DONE │
└───────┬───────────────────┬──────────────────────┬───────────┘
        │                   │                      │
┌───────┴──────┐   ┌────────┴────────┐   ┌─────────┴─────────┐
│ AGENT 1      │   │ AGENT 2         │   │ AGENT 3           │
│ Context &RAG │   │ Teaching &      │   │ Assessment &      │
│ + Concept DAG│   │ Pedagogy        │   │ Misconception     │
└───────┬──────┘   └────────┬────────┘   └─────────┬─────────┘
        └───────────────────┴──────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│ MEDIA:  Deepgram STT → ElevenLabs TTS → HeyGen/LivePortrait  │
│         → viseme-driven canvas avatar (always-on fallback)   │
└──────────────────────────────────────────────────────────────┘
```

**Two entry points, one pipeline.** Uploaded documents and bare topics converge on the same
`KnowledgeGraph` contract, so planning, teaching, assessment and analytics are written once.

## 3. Key features

| # | Feature | Where |
|---|---|---|
| §3 | PDF / DOCX / PPTX / MD / TXT ingest, RAG-grounded | `ingest/parser.py`, `ingest/vector_store.py` |
| §4 | Topic-based teaching with **no** uploaded material | `agents/topic_planner.py` |
| §5 | Human teaching loop with re-explanation | `core/orchestrator.py` |
| §6 | Beginner / Intermediate / Advanced personalization | `agents/agent2_teaching.py` (`LEVEL_STYLE`) |
| §7 | Time-based lesson shaping (5 / 20 / 60 min) | `TeachingAgent.plan` |
| §8 | 18 languages + mid-lesson switching + cross-lingual RAG | `core/i18n.py` |
| §9 | Avatar video, voice, on-screen text & visuals | `media/`, `components/Avatar.tsx` |
| §10 | Subject-aware visuals (math/physics/bio/history/code) | `SUBJECT_VISUALS`, `infer_subject` |
| §11 | Mid-lesson questioning; answers steer what happens next | `agents/agent3_assessment.py` |
| §12 | Named misconception diagnosis + different-analogy re-teach | `Orchestrator._remediate` |
| §13 | Graded learning report | `Orchestrator.build_report` |
| §14 | Student learning profile & mastery model | `StudentProfile`, `ConceptMastery` |
| §15 | AI-generated learning path | `AssessmentAgent._next_steps` |

## 4. AI/ML models used

| Role | Primary | Fallback (no key) |
|---|---|---|
| Reasoning / lesson authoring | OpenAI `gpt-4o-mini` or Anthropic `claude-3-5-sonnet` | deterministic extractive lesson builder |
| Embeddings / retrieval | hashed n-gram random projection + BM25 | same (no model download needed) |
| TTS | ElevenLabs `eleven_turbo_v2_5` (multilingual) | syllable-weighted timing simulation |
| STT | Deepgram `nova-2` (language-tagged) | disabled, typed input still works |
| Avatar | HeyGen API → LivePortrait/SadTalker worker | viseme-driven canvas avatar |

## 5. RAG implementation

1. **Parse** — PyMuPDF for PDF; DOCX/PPTX are unzipped and parsed from XML directly (no
   heavyweight deps), recovering heading styles so section structure survives. The container
   is **sniffed** (`PK`, `%PDF-`) so a mislabeled extension degrades instead of crashing.
2. **Chunk** — section-aware sliding window (~1100 chars, 150 overlap) snapped to sentence
   boundaries. Beats fixed-size splitting on retrieval precision.
3. **Index** — **hybrid**: BM25 lexical + dense cosine over hashed n-gram projections.
4. **Fuse** — **Reciprocal Rank Fusion** (`1/(60+rank)`), robust to score-scale mismatch
   between the two retrievers.
5. **Ground** — Agent 2 receives only retrieved chunks and is instructed never to exceed
   them. Student Q&A cites page numbers.

**Cross-lingual grounding (§8).** The corpus is *never* translated — that would degrade
retrieval. Retrieval runs in the document's language; the teaching agent receives
source-language context plus an instruction to *explain in* the target language. English
textbook → Hindi teaching works without touching the index.

## 6. Prompt / agent architecture

- **Agent 1 (Context & RAG)** — mines concepts, proposes a prerequisite DAG. Every proposed
  edge is validated: **any edge that would create a cycle is dropped**, so the planner always
  receives a true DAG. Kahn topological sort with `(difficulty, index)` tie-breaking.
- **Agent 2 (Pedagogy)** — allocates the time budget by
  `difficulty × prerequisite-centrality × (1 − live mastery)`, renormalized to hit the budget
  exactly. Emits narration plus visual blocks carrying **character-level cue points**.
- **Agent 3 (Assessment)** — MCQs graded locally (zero latency/cost); open answers graded
  semantically. Every distractor maps to a **named misconception**.

`llm.json_call` repairs fenced/truncated JSON and always returns a usable object, so no agent
can be broken by a malformed model response.

## 7. Personalization approach

Level rewrites the teaching contract, not just the tone: **beginner** forbids unexplained
jargon and caps formulas; **advanced** requires mathematics, edge cases and trade-offs.
Time budget changes lesson *structure* (5 min → overview only; 60 min → deep + assessment).
After every answer, only the **unteached tail** of the plan is re-allocated against live
mastery — the session keeps its time budget while spending more of it where you're weak.

## 8. Assessment methodology

- **Mastery** — exponentially-weighted update with a decaying learning rate
  `m ← m + α(score − m)`, `α = 1/(1 + 0.7·(attempts−1))`. Converges fast but resists a single
  lucky guess (verified in tests).
- **Misconception diagnosis (§12)** — a wrong MCQ option resolves to a *named* misconception
  (`sign-error`, `concept-conflation`, …), which is fed back into Agent 2 with an explicit
  instruction to name it, refute it with a counter-example, and re-teach using a **completely
  different analogy**. Up to 2 attempts, each shorter and simpler, then the lesson moves on so
  a stuck student never blocks the session.
- **Learning path (§15)** — a gap is only actionable once its prerequisites are mastered;
  otherwise the system recommends the prerequisite first.

## 9. Multilingual implementation

18 languages (English, Hindi, Hinglish, Tamil, Telugu, Kannada, Malayalam, Marathi, Bengali,
Gujarati, Punjabi, Urdu, Spanish, French, German, Arabic, Chinese, Japanese).

- Switch from the UI **or naturally in conversation** — `"Mujhe ye Hinglish mein samjhao"`
  is detected and applied.
- **Context is preserved** across a switch: cursor, plan, mastery and DAG are untouched
  (explicitly asserted by `test_language_switch_preserves_lesson_context`).
- Hinglish is handled as a first-class register (Latin script, English technical terms).
- Non-Latin scripts use a slower words-per-minute constant so timing, captions and lip-sync
  stay accurate.

## 10. Voice & avatar implementation

TTS emits a **word-level timing track** (syllable-weighted, punctuation-aware) plus a
**viseme track**. The frontend binary-searches that track each animation frame to drive
caption highlighting, canvas cue points and the avatar's mouth **off a single clock** — so
audio, visuals and lip movement stay in sync whether the audio is real ElevenLabs output or
the offline simulation. Three avatar tiers (HeyGen → LivePortrait worker → canvas rig) expose
one uniform contract to the client.

## 11. APIs and third-party services

| Service | Used for | Required? |
|---|---|---|
| OpenAI / Anthropic | lesson authoring, concept extraction, grading | No |
| ElevenLabs | multilingual neural TTS | No |
| Deepgram | speech-to-text | No |
| HeyGen / LivePortrait | photoreal talking-head video | No |
| PyMuPDF, FastAPI, Pydantic, Next.js, React, Tailwind, KaTeX, Mermaid | core stack | Yes (bundled) |

No paid service is required for a complete demonstration.

## 12. Setup instructions

```bash
git clone <repo> && cd AI-AUTOMATED-TEACHING-AGENT
./run.sh          # backend :8000 + frontend :3000
```

Manual:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

cd frontend && npm install && npm run dev
```

Open <http://localhost:3000>. Try `samples/ml_notes.md`, or switch to **Teach a topic** and
enter *"Newton's Laws of Motion"* with no file at all.

Optional keys: copy `.env.example` → `backend/.env`.

## 13. Deployment

```bash
cp .env.example .env      # optional keys
docker compose up --build # frontend :3000, backend :8000
```

The frontend proxies `/api` and `/media` to the backend, so only port 3000 needs to be
public. Both containers bind `0.0.0.0`.

## 14. Testing

```bash
cd backend && .venv/bin/python -m pytest tests -q     # 51 passed
```

Covers chunking, DOCX/PPTX extraction, mislabeled-file fallback, hybrid retrieval ranking,
DAG cycle removal, topological ordering, time-budget adherence across 5/20/60 min, depth
escalation, subject inference, subject-specific visual grammar, language resolution, natural
conversational language switching, **context preservation across a language switch**,
misconception mapping, mastery convergence, prerequisite-aware recommendations, capped
multi-attempt remediation, learning-report shape, JSON repair, and full offline session loops
for **both** document and topic entry points.

## 15. Known limitations

- **Offline lesson quality.** With no LLM key, narration is extracted from the source rather
  than freshly authored — grounded and never hallucinated, but flatter than the LLM path.
  Topic mode without a key returns a pedagogical *scaffold* and says so, rather than
  inventing facts.
- **Offline translation.** `i18n.translate` needs an LLM; without a key the UI, timing and
  voice-language plumbing all switch correctly but narration text stays in English.
- **Avatar tier.** The default canvas avatar is a stylized rig, not photoreal; photoreal
  requires a HeyGen key or a LivePortrait worker.
- **Scanned PDFs** have no text layer — OCR is not wired in; ingest returns a clean 422.
- **Sessions are in-memory**, so they reset on restart. `StudentProfile` is already
  serializable for a Postgres-backed long-term memory (§18) as the next step.
- **Video is composed client-side** (avatar + synced canvas) rather than rendered to a single
  downloadable MP4 file.

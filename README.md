# AI Automated Teaching Agent

A multi-agent system that ingests any course document and delivers a **live, adaptive,
narrated lesson** with a talking avatar, synchronized LaTeX/code/diagram canvas,
misconception-aware assessment and a student analytics dashboard.

> **Runs with zero API keys.** Every external service (LLM, TTS, STT, avatar video) has a
> deterministic local fallback, so the demo never fails on stage. Add keys to upgrade
> each tier in place — no code changes.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  FRONTEND (Next.js 14 · React 18 · Tailwind)                 │
│  Avatar · Synchronized Canvas (KaTeX/Mermaid/Code) · Dash    │
└───────────────┬──────────────────────────┬───────────────────┘
       WebSocket events              Media stream (audio/video)
┌───────────────┴──────────────────────────┴───────────────────┐
│  BACKEND ORCHESTRATOR  (FastAPI · explicit finite state machine)│
│  IDLE→INGESTING→PLANNING→TEACHING⇄ASSESSING⇄REMEDIATING→DONE  │
└───────┬───────────────────┬──────────────────────┬───────────┘
        │                   │                      │
┌───────┴──────┐   ┌────────┴────────┐   ┌─────────┴─────────┐
│ AGENT 1      │   │ AGENT 2         │   │ AGENT 3           │
│ Context &RAG │   │ Teaching &      │   │ Assessment &      │
│ Ingest + DAG │   │ Pedagogy        │   │ Misconception     │
└───────┬──────┘   └────────┬────────┘   └─────────┬─────────┘
        └───────────────────┴──────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│ AVATAR & MEDIA:  Deepgram STT → ElevenLabs TTS →             │
│                  HeyGen/LivePortrait → WebRTC/HTTP           │
└──────────────────────────────────────────────────────────────┘
```

### Agent responsibilities

| Agent | Does | Key algorithms |
|---|---|---|
| **1 · Context & RAG** | parse → chunk → index → concept extraction → prerequisite DAG | section-aware sliding-window chunking; **hybrid BM25 + dense retrieval fused with Reciprocal Rank Fusion**; TF-IDF keyphrase mining; **cycle-safe DAG construction**; Kahn topological sort |
| **2 · Teaching & Pedagogy** | time/depth allocation; narration + synchronized visuals | budget-constrained weighted allocation over difficulty × prerequisite-centrality × live mastery; **character-level cue points** binding visuals to narration |
| **3 · Assessment** | grade, diagnose misconception, model mastery, suggest path | distractor→misconception mapping; **decaying-α exponential mastery update**; prerequisite-aware learning-path recommendation |

---

## Quick start

```bash
# Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev            # http://localhost:3000
```

Or one command: `./run.sh`

Then upload `samples/ml_notes.md` (or any PDF) and press **Start teaching**.

### Optional API keys

Copy `.env.example` → `backend/.env` and fill in whichever you have:

| Variable | Upgrades |
|---|---|
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | LLM concept extraction, lesson authoring, open-answer grading |
| `ELEVENLABS_API_KEY` | real neural TTS (otherwise timing is simulated) |
| `DEEPGRAM_API_KEY` | voice questions from the student |
| `HEYGEN_API_KEY` / `AVATAR_WORKER_URL` | photoreal talking-head video (otherwise viseme canvas avatar) |

`GET /api/health` reports exactly which tier is active.

---

## Design decisions worth noting

**Graceful degradation is a feature, not a fallback.** Each capability is a tier; the
orchestrator picks the best available at boot and the frontend renders one uniform
contract either way. A judge with no network still sees the complete product.

**The LLM is never trusted blindly.** `json_call` repairs fenced/truncated JSON and
always returns a usable object. Proposed DAG edges are validated and any edge that
would create a cycle is dropped, so the planner always receives a true DAG.

**Audio/visual sync without a media server.** The TTS layer emits a word-level timing
track (syllable-weighted, punctuation-aware) plus a viseme track. The frontend binary-searches
that track each frame to drive caption highlighting, canvas cue points and the avatar's
mouth off a single clock — identical behaviour whether the audio is real or simulated.

**Adaptive re-planning.** After each assessment only the *unteached* tail of the lesson
plan is re-allocated against live mastery, so the session always respects its time budget
while spending more of it where the student is weak.

---

## API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | status + active capability tiers |
| `POST` | `/api/sessions` | create a session (`{minutes}`) |
| `POST` | `/api/sessions/{id}/ingest` | upload document → DAG + lesson plan |
| `POST` | `/api/sessions/{id}/next` | advance the FSM one concept |
| `POST` | `/api/sessions/{id}/answer` | submit an answer → evaluation + profile |
| `POST` | `/api/sessions/{id}/ask` | student interrupts with a question (RAG-grounded) |
| `POST` | `/api/sessions/{id}/transcribe` | audio → text (Deepgram) |
| `GET`  | `/api/sessions/{id}/profile` | student analytics |
| `WS`   | `/api/ws/{id}` | live event stream (state, turns, questions, evaluations) |

Interactive docs at `/docs`.

---

## Tests

```bash
cd backend && .venv/bin/python -m pytest tests -q     # 17 passed
```

Covers chunking, hybrid retrieval ranking, DAG cycle removal, topological ordering,
time-budget adherence, misconception mapping, mastery convergence, prerequisite-aware
recommendations, timing monotonicity, JSON repair, and two full offline session loops
(including the remediation branch).

---

## Roadmap status

| Phase | Deliverable | Status |
|---|---|---|
| 1 | Document parsing, vector store, DAG | done |
| 2 | Time/depth engine, misconception framework, prompts | done |
| 3 | LaTeX/Mermaid/code sync, TTS + STT | done |
| 4 | Avatar + real-time A/V sync | done (3 tiers) |
| 5 | Analytics dashboard, score breakdown, learning paths | done |

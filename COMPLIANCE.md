# Requirement Compliance Matrix
Round 2 Technical Assessment — "AI Teacher: Build a Human-Like AI Educator"

## §17 Mandatory Requirements

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Learning from uploaded material | ✅ | `ingest/parser.py` (PDF/DOCX/PPTX/MD/TXT) + hybrid RAG; `POST /api/sessions/{id}/ingest` |
| 2 | Topic-based teaching | ✅ | `agents/topic_planner.py`; `POST /api/sessions/{id}/topic` — no file needed |
| 3 | AI-generated lesson structure | ✅ | concept DAG + `TeachingAgent.plan`; Plan tab in UI |
| 4 | Personalized teaching | ✅ | `LearnerProfile` (level, language, time, objective, style, prior knowledge) |
| 5 | Human-like teaching interaction | ✅ | FSM teach→question→evaluate→remediate→adapt loop |
| 6 | Video-based AI Teacher presentation | ✅ | avatar + synced canvas + captions, single playback clock |
| 7 | AI voice | ✅ | ElevenLabs multilingual TTS; simulated timing track offline |
| 8 | Human-like AI avatar | ✅ | 3 tiers: HeyGen → LivePortrait → viseme-driven canvas rig |
| 9 | Multilingual capability | ✅ | 18 languages, mid-lesson switching, cross-lingual RAG, Hinglish |
| 10 | Student questioning and assessment | ✅ | mid-lesson MCQs + final quiz weighted to weak concepts |
| 11 | Adaptive response to performance | ✅ | tail re-planning by live mastery; difficulty & depth adjust |
| 12 | Working application/prototype | ✅ | `./run.sh`; 51 passing tests; runs with zero API keys |

## §19 Evaluation Criteria Coverage

| Area | Wt | How this submission addresses it |
|---|---|---|
| Human-Like Teaching & Adaptation | 20 | Full Understand→Plan→Explain→Question→Evaluate→Adapt loop. Misconceptions are *named*, refuted with a counter-example, and re-taught with a **different analogy** (max 2 attempts, each simpler). Only the unteached tail is re-planned, so adaptation respects the time budget. |
| AI/ML and LLM Implementation | 15 | Provider-agnostic gateway (OpenAI/Anthropic) with retry + JSON repair; 3-agent architecture; cycle-safe DAG; decaying-α mastery model; every LLM output validated before use. |
| RAG and Knowledge Grounding | 15 | Section-aware chunking → hybrid BM25 + dense → **Reciprocal Rank Fusion**; answers cite pages; agent instructed never to exceed retrieved context; corpus never translated to protect retrieval fidelity. |
| AI Teaching Video Generation | 15 | Avatar + subject-appropriate visuals (LaTeX/Mermaid/code) revealed at **character-level cue points**, driven off one clock with captions — not a talking head over static text. |
| Multilingual Capability | 10 | 18 languages incl. 11 Indian; natural in-conversation switching; **lesson context provably preserved** across a switch; script-aware speaking rates. |
| Voice and AI Avatar | 10 | Word-level timing + viseme track drive lip-sync; multilingual TTS; 3-tier avatar with one uniform client contract. |
| Innovation and Originality | 5 | Zero-dependency graceful degradation; cross-lingual grounding without translating the index; cue-point A/V sync with no media server; cycle-safe DAG validation. |
| User Experience and Interface | 5 | One-screen intake (upload *or* topic, level, time, language); live agent trace; Lesson/Plan/Dashboard tabs; interrupt-and-ask. |
| Documentation & Technical Presentation | 5 | README covers all 15 required §20 sections incl. known limitations; this matrix; 51 tests. |

## §18 Advanced Features Implemented

- Concept maps (prerequisite DAG visualization)
- Learning analytics (mastery, score breakdown, timeline)
- Coding demonstrations (subject-aware code blocks with execution-flow diagrams)
- Automatic study planner (prerequisite-aware learning path)
- Offline/local AI models (full zero-key operation)
- Interactive diagrams (Mermaid, rendered per subject)

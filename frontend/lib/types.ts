export type BlockType = "text" | "latex" | "code" | "mermaid" | "image";

export interface VisualBlock {
  type: BlockType;
  content: string;
  language: string;
  caption: string;
  cue_at_char: number;
}

export interface WordTiming { word: string; start: number; end: number; char: number }
export interface Viseme { t: number; shape: string }

export interface AudioTrack {
  audio_url: string | null;
  timings: WordTiming[];
  visemes: Viseme[];
  duration: number;
  engine: string;
}

export interface Question {
  id: string;
  concept_id: string;
  prompt: string;
  kind: "mcq" | "open";
  options: string[];
  answer_index: number | null;
  bloom: string;
}

export interface TeachingTurn {
  concept_id: string;
  concept: string;
  depth: string;
  minutes: number;
  narration: string;
  blocks: VisualBlock[];
  audio: AudioTrack;
  avatar: { mode: string; idle?: string; video_url?: string };
  progress: { index: number; total: number };
}

export interface Evaluation {
  question_id: string;
  concept_id: string;
  correct: boolean;
  score: number;
  misconception: string | null;
  feedback: string;
  remediate: boolean;
}

export interface ConceptMastery {
  concept_id: string; name: string; attempts: number;
  score: number; mastery: number; misconceptions: string[];
}

export interface StudentProfile {
  session_id: string;
  mastery: Record<string, ConceptMastery>;
  overall: number;
  strengths: string[];
  gaps: string[];
  next_steps: string[];
  timeline: { concept: string; score: number; misconception: string | null }[];
}

export interface Concept {
  id: string; name: string; summary: string; difficulty: number;
  est_minutes: number; prerequisites: string[]; keywords: string[];
}

export interface KnowledgeGraph {
  doc_id: string; concepts: Concept[]; order: string[];
  subject: string; title: string; source: string;
}

export interface PlanItem {
  concept_id: string; name: string; minutes: number; depth: string; rationale: string;
}
export interface LessonPlan { session_id: string; total_minutes: number; items: PlanItem[] }

export interface WSEvent { type: string; payload: any }

export type Level = "beginner" | "intermediate" | "advanced";

export interface LearnerProfile {
  level: Level;
  language: string;
  language_name: string;
  minutes: number;
  objective: string;
  style: string;
  prior_knowledge: string;
}

export interface LanguageOption { code: string; name: string; native: string }

export interface LearningReport {
  topic: string;
  score_pct: number;
  grade: string;
  concepts_understood: string[];
  weak_areas: string[];
  incorrect_concepts: string[];
  misconceptions: string[];
  recommended_revision: string[];
  suggested_next_topic: string;
  time_spent_minutes: number;
  summary: string;
}

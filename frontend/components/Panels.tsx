"use client";
import { useState } from "react";
import type { Evaluation, KnowledgeGraph, LessonPlan, Question, StudentProfile } from "@/lib/types";

/* ------------------------------------------------------- knowledge graph */
export function GraphPanel({ graph }: { graph: KnowledgeGraph }) {
  const pos = graph.order.map((id, i) => ({ id, i }));
  const byId = Object.fromEntries(graph.concepts.map((c) => [c.id, c]));
  return (
    <div className="rounded-xl border border-edge bg-panel p-4">
      <h3 className="mb-3 text-xs uppercase tracking-widest text-zinc-500">Prerequisite DAG</h3>
      <div className="space-y-1.5">
        {pos.map(({ id, i }) => {
          const c = byId[id]; if (!c) return null;
          return (
            <div key={id} className="flex items-center gap-2 text-sm">
              <span className="w-5 text-right font-mono text-[10px] text-zinc-600">{i + 1}</span>
              <div className="h-1.5 rounded-full bg-accent2"
                   style={{ width: `${8 + c.difficulty * 60}px`, opacity: 0.35 + c.difficulty * 0.6 }} />
              <span className="truncate text-zinc-300">{c.name}</span>
              {c.prerequisites.length > 0 && (
                <span className="font-mono text-[10px] text-zinc-600">
                  ← {c.prerequisites.map((p) => byId[p]?.name?.slice(0, 12) ?? p).join(", ")}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ lesson plan */
export function PlanPanel({ plan, current }: { plan: LessonPlan; current: number }) {
  return (
    <div className="rounded-xl border border-edge bg-panel p-4">
      <h3 className="mb-3 flex justify-between text-xs uppercase tracking-widest text-zinc-500">
        <span>Time / Depth Allocation</span><span>{plan.total_minutes}m</span>
      </h3>
      <div className="space-y-2">
        {plan.items.map((it, i) => (
          <div key={it.concept_id}
               className={`rounded-lg border p-2 text-sm ${i === current
                 ? "border-accent bg-accent/5" : "border-edge"}`}>
            <div className="flex justify-between">
              <span className="truncate text-zinc-200">{it.name}</span>
              <span className="font-mono text-xs text-zinc-500">{it.minutes}m · {it.depth}</span>
            </div>
            <div className="mt-0.5 text-[11px] text-zinc-600">{it.rationale}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- question */
export function QuestionCard({
  question, evaluation, onAnswer,
}: { question: Question | null; evaluation: Evaluation | null; onAnswer: (a: number | string) => void }) {
  const [sel, setSel] = useState<number | null>(null);
  const [text, setText] = useState("");
  if (!question && !evaluation) return null;

  if (evaluation && !question) {
    return (
      <div className={`rounded-xl border p-4 ${evaluation.correct
        ? "border-accent/50 bg-accent/5" : "border-warn/50 bg-warn/5"}`}>
        <div className="text-xs uppercase tracking-widest text-zinc-500">
          {evaluation.correct ? "Correct" : "Misconception detected"}
        </div>
        <p className="mt-1 text-sm text-zinc-200">{evaluation.feedback}</p>
        {evaluation.misconception && (
          <span className="mt-2 inline-block rounded-full border border-warn/40 px-2 py-0.5 font-mono text-[10px] text-warn">
            {evaluation.misconception}
          </span>
        )}
      </div>
    );
  }
  if (!question) return null;

  return (
    <div className="rounded-xl border border-accent2/50 bg-accent2/5 p-4">
      <div className="text-xs uppercase tracking-widest text-zinc-500">
        Check for understanding · {question.bloom}
      </div>
      <p className="mt-1 mb-3 text-sm text-zinc-100">{question.prompt}</p>
      {question.kind === "mcq" ? (
        <div className="space-y-1.5">
          {question.options.map((o, i) => (
            <button key={i} onClick={() => { setSel(i); onAnswer(i); }}
              className={`block w-full rounded-lg border p-2 text-left text-sm transition
                ${sel === i ? "border-accent2" : "border-edge hover:border-zinc-500"}`}>
              <span className="mr-2 font-mono text-xs text-zinc-600">{String.fromCharCode(65 + i)}</span>
              {o}
            </button>
          ))}
        </div>
      ) : (
        <div className="flex gap-2">
          <input value={text} onChange={(e) => setText(e.target.value)}
            className="flex-1 rounded-lg border border-edge bg-black/40 px-3 py-2 text-sm"
            placeholder="your answer…" />
          <button onClick={() => onAnswer(text)}
            className="rounded-lg bg-accent2 px-3 py-2 text-sm font-medium text-black">submit</button>
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------- dashboard */
export function Dashboard({ profile }: { profile: StudentProfile }) {
  const rows = Object.values(profile.mastery);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        {[
          ["Overall mastery", `${Math.round(profile.overall * 100)}%`],
          ["Strengths", String(profile.strengths.length)],
          ["Gaps", String(profile.gaps.length)],
        ].map(([k, v]) => (
          <div key={k} className="rounded-xl border border-edge bg-panel p-4">
            <div className="text-[10px] uppercase tracking-widest text-zinc-500">{k}</div>
            <div className="mt-1 text-2xl font-semibold text-accent">{v}</div>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-edge bg-panel p-4">
        <h3 className="mb-3 text-xs uppercase tracking-widest text-zinc-500">Score breakdown</h3>
        <div className="space-y-2">
          {rows.map((m) => (
            <div key={m.concept_id}>
              <div className="flex justify-between text-sm">
                <span className="text-zinc-300">{m.name}</span>
                <span className="font-mono text-xs text-zinc-500">
                  {Math.round(m.mastery * 100)}% · {m.attempts} attempt{m.attempts === 1 ? "" : "s"}
                </span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-edge">
                <div className={`h-full ${m.mastery >= 0.7 ? "bg-accent" : "bg-warn"}`}
                     style={{ width: `${Math.max(3, m.mastery * 100)}%` }} />
              </div>
              {m.misconceptions.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {m.misconceptions.map((x) => (
                    <span key={x} className="rounded-full border border-warn/30 px-1.5 py-0.5 font-mono text-[10px] text-warn">
                      {x}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
          {!rows.length && <p className="text-sm text-zinc-600">No assessments yet.</p>}
        </div>
      </div>

      {profile.next_steps.length > 0 && (
        <div className="rounded-xl border border-edge bg-panel p-4">
          <h3 className="mb-2 text-xs uppercase tracking-widest text-zinc-500">
            Suggested learning path
          </h3>
          <ol className="space-y-1.5">
            {profile.next_steps.map((s, i) => (
              <li key={i} className="flex gap-2 text-sm text-zinc-300">
                <span className="font-mono text-xs text-accent2">{i + 1}.</span>{s}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

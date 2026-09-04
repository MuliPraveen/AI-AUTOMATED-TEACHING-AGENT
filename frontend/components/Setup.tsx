"use client";
/** Learner intake (§4 topic mode, §6 level, §7 time, §8 language). */
import { useEffect, useRef, useState } from "react";
import type { LanguageOption, Level } from "@/lib/types";

const LEVELS: { id: Level; label: string; hint: string }[] = [
  { id: "beginner", label: "Beginner", hint: "simple terms & analogies" },
  { id: "intermediate", label: "Intermediate", hint: "technical + practical examples" },
  { id: "advanced", label: "Advanced", hint: "maths, edge cases, implementation" },
];

const TIMES = [5, 20, 60];

export function Setup({
  onStart, busy,
}: {
  busy: boolean;
  onStart: (input: { file?: File | null; topic?: string }, learner: any) => void;
}) {
  const [mode, setMode] = useState<"upload" | "topic">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [topic, setTopic] = useState("");
  const [level, setLevel] = useState<Level>("beginner");
  const [minutes, setMinutes] = useState(20);
  const [language, setLanguage] = useState("en");
  const [objective, setObjective] = useState("");
  const [langs, setLangs] = useState<LanguageOption[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch("/api/languages").then((r) => r.json())
      .then((d) => setLangs(d.languages)).catch(() => {});
  }, []);

  const ready = mode === "upload" ? !!file : topic.trim().length > 2;

  return (
    <div className="mx-auto max-w-2xl rounded-2xl border border-edge bg-panel p-8">
      <h2 className="text-sm uppercase tracking-widest text-zinc-500">New teaching session</h2>
      <p className="mt-1 mb-5 text-sm text-zinc-400">
        Upload material or name a topic. The AI Teacher plans the lesson, teaches it with
        voice and visuals, questions you, and adapts to your answers.
      </p>

      {/* mode */}
      <div className="mb-4 flex gap-1 rounded-xl border border-edge p-1 text-xs">
        {(["upload", "topic"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)}
            className={`flex-1 rounded-lg px-3 py-2 uppercase tracking-widest ${
              mode === m ? "bg-accent text-black" : "text-zinc-400 hover:text-zinc-200"}`}>
            {m === "upload" ? "Upload material" : "Teach a topic"}
          </button>
        ))}
      </div>

      {mode === "upload" ? (
        <div onClick={() => fileInput.current?.click()}
             onDragOver={(e) => e.preventDefault()}
             onDrop={(e) => { e.preventDefault(); setFile(e.dataTransfer.files[0] ?? null); }}
             className="cursor-pointer rounded-xl border border-dashed border-edge p-8 text-center hover:border-accent">
          <input ref={fileInput} type="file" accept=".pdf,.md,.txt,.docx,.pptx" hidden
                 onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <p className="text-sm text-zinc-300">{file ? file.name : "drop a file or click to browse"}</p>
          <p className="mt-1 text-xs text-zinc-600">pdf · docx · pptx · md · txt (max 25 MB)</p>
        </div>
      ) : (
        <div>
          <input value={topic} onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. Teach me Newton's Laws / React for interviews"
            className="w-full rounded-xl border border-edge bg-black/40 px-4 py-3 text-sm" />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {["Newton's Laws of Motion", "Photosynthesis", "React Hooks", "Ohm's Law"].map((t) => (
              <button key={t} onClick={() => setTopic(t)}
                className="rounded-full border border-edge px-2.5 py-1 text-[11px] text-zinc-400 hover:border-accent hover:text-accent">
                {t}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* level */}
      <label className="mt-6 block text-[10px] uppercase tracking-widest text-zinc-500">
        Your level
      </label>
      <div className="mt-2 grid grid-cols-3 gap-2">
        {LEVELS.map((l) => (
          <button key={l.id} onClick={() => setLevel(l.id)}
            className={`rounded-lg border p-2 text-left ${level === l.id
              ? "border-accent bg-accent/5" : "border-edge hover:border-zinc-500"}`}>
            <div className="text-xs text-zinc-200">{l.label}</div>
            <div className="text-[10px] leading-tight text-zinc-600">{l.hint}</div>
          </button>
        ))}
      </div>

      {/* time + language */}
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <div>
          <label className="block text-[10px] uppercase tracking-widest text-zinc-500">
            Time available: <span className="text-accent">{minutes} min</span>
          </label>
          <input type="range" min={5} max={90} step={5} value={minutes}
                 onChange={(e) => setMinutes(+e.target.value)}
                 className="mt-2 w-full accent-emerald-400" />
          <div className="mt-1 flex gap-1">
            {TIMES.map((t) => (
              <button key={t} onClick={() => setMinutes(t)}
                className="rounded border border-edge px-2 py-0.5 text-[10px] text-zinc-500 hover:border-accent">
                {t}m
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-widest text-zinc-500">
            Teaching language
          </label>
          <select value={language} onChange={(e) => setLanguage(e.target.value)}
            className="mt-2 w-full rounded-lg border border-edge bg-black/40 px-3 py-2 text-sm">
            {(langs.length ? langs : [{ code: "en", name: "English", native: "English" }])
              .map((l) => (
                <option key={l.code} value={l.code}>{l.name} — {l.native}</option>
              ))}
          </select>
          <p className="mt-1 text-[10px] text-zinc-600">
            material may be in any language
          </p>
        </div>
      </div>

      <input value={objective} onChange={(e) => setObjective(e.target.value)}
        placeholder="Optional: your goal, e.g. 'prepare for a unit test'"
        className="mt-4 w-full rounded-lg border border-edge bg-black/40 px-3 py-2 text-xs" />

      <button disabled={!ready || busy}
        onClick={() => onStart(
          mode === "upload" ? { file } : { topic },
          { level, minutes, language, objective },
        )}
        className="mt-6 w-full rounded-xl bg-accent py-3 text-sm font-semibold text-black disabled:opacity-40">
        {busy ? "planning your lesson…" : "Start teaching"}
      </button>
    </div>
  );
}

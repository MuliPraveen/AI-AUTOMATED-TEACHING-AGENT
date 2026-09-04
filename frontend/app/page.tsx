"use client";
import { useEffect, useRef, useState } from "react";
import { useSession } from "@/lib/useSession";
import { Lesson } from "@/components/Lesson";
import { Dashboard, GraphPanel, PlanPanel, QuestionCard } from "@/components/Panels";

type Tab = "lesson" | "plan" | "dashboard";

export default function Home() {
  const s = useSession();
  const [file, setFile] = useState<File | null>(null);
  const [minutes, setMinutes] = useState(15);
  const [tab, setTab] = useState<Tab>("lesson");
  const [auto, setAuto] = useState(true);
  const [ask, setAsk] = useState("");
  const [asked, setAsked] = useState<{ q: string; a: string } | null>(null);
  const [caps, setCaps] = useState<any>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => { fetch("/api/health").then((r) => r.json()).then(setCaps).catch(() => {}); }, []);

  const begin = async () => {
    if (!file) return;
    const sid = await s.start(file, minutes);
    if (sid) setTimeout(() => s.next(), 400);
  };

  const onTurnDone = () => { if (auto && !s.question) s.next(); };

  const cur = s.plan && s.turn
    ? s.plan.items.findIndex((i) => i.concept_id === s.turn!.concept_id) : -1;

  return (
    <main className="mx-auto max-w-[1400px] p-6">
      {/* header */}
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">
            AI Automated Teaching Agent
          </h1>
          <p className="font-mono text-[11px] text-zinc-500">
            Agent 1 Context/RAG · Agent 2 Pedagogy · Agent 3 Assessment
          </p>
        </div>
        <div className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-widest">
          <span className="rounded-full border border-edge px-2 py-1">
            state: <span className="text-accent">{s.state}</span>
          </span>
          {caps && (
            <span className="rounded-full border border-edge px-2 py-1 text-zinc-500">
              llm {caps.capabilities.llm ? "on" : "local"} · tts{" "}
              {caps.capabilities.tts ? "on" : "sim"} · avatar {caps.capabilities.avatar_mode}
            </span>
          )}
        </div>
      </header>

      {/* setup */}
      {!s.sessionId && (
        <div className="mx-auto max-w-xl rounded-2xl border border-edge bg-panel p-8">
          <h2 className="mb-1 text-sm uppercase tracking-widest text-zinc-500">Start a session</h2>
          <p className="mb-5 text-sm text-zinc-400">
            Upload course material (PDF, Markdown or text). The agents extract a concept
            DAG, allocate teaching time, then deliver a live narrated lesson.
          </p>
          <div onClick={() => fileInput.current?.click()}
               onDragOver={(e) => e.preventDefault()}
               onDrop={(e) => { e.preventDefault(); setFile(e.dataTransfer.files[0] ?? null); }}
               className="cursor-pointer rounded-xl border border-dashed border-edge p-8 text-center hover:border-accent">
            <input ref={fileInput} type="file" accept=".pdf,.md,.txt" hidden
                   onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <p className="text-sm text-zinc-300">{file ? file.name : "drop a file or click to browse"}</p>
            <p className="mt-1 text-xs text-zinc-600">pdf · md · txt (max 25 MB)</p>
          </div>
          <label className="mt-5 block text-xs uppercase tracking-widest text-zinc-500">
            Session length: <span className="text-accent">{minutes} min</span>
          </label>
          <input type="range" min={5} max={60} step={5} value={minutes}
                 onChange={(e) => setMinutes(+e.target.value)} className="mt-2 w-full accent-emerald-400" />
          <button disabled={!file || s.busy} onClick={begin}
            className="mt-5 w-full rounded-xl bg-accent py-3 text-sm font-semibold text-black disabled:opacity-40">
            {s.busy ? "ingesting & planning…" : "Start teaching"}
          </button>
        </div>
      )}

      {/* session */}
      {s.sessionId && (
        <div className="grid gap-5 lg:grid-cols-[1fr_330px]">
          <div className="space-y-4">
            <nav className="flex gap-1 rounded-xl border border-edge bg-panel p-1 text-xs">
              {(["lesson", "plan", "dashboard"] as Tab[]).map((t) => (
                <button key={t} onClick={() => setTab(t)}
                  className={`flex-1 rounded-lg px-3 py-2 uppercase tracking-widest ${
                    tab === t ? "bg-accent text-black" : "text-zinc-400 hover:text-zinc-200"}`}>
                  {t}
                </button>
              ))}
            </nav>

            {tab === "lesson" && (
              <>
                {s.turn ? <Lesson turn={s.turn} onDone={onTurnDone} />
                  : <div className="rounded-xl border border-dashed border-edge p-16 text-center text-sm text-zinc-600">
                      preparing the first concept…
                    </div>}
                <QuestionCard question={s.question} evaluation={s.evaluation} onAnswer={s.answer} />
                {s.state === "complete" && s.quiz.length > 0 && (
                  <div className="rounded-xl border border-edge bg-panel p-4">
                    <h3 className="mb-3 text-xs uppercase tracking-widest text-zinc-500">
                      Final assessment
                    </h3>
                    <ol className="space-y-3">
                      {s.quiz.map((q, i) => (
                        <li key={q.id} className="text-sm">
                          <span className="font-mono text-xs text-accent2">Q{i + 1}.</span> {q.prompt}
                          <ul className="mt-1 space-y-0.5 pl-6 text-xs text-zinc-500">
                            {q.options.map((o, j) => (
                              <li key={j} className={j === q.answer_index ? "text-accent" : ""}>
                                {String.fromCharCode(65 + j)}. {o}
                              </li>
                            ))}
                          </ul>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
              </>
            )}

            {tab === "plan" && (
              <div className="space-y-4">
                {s.plan && <PlanPanel plan={s.plan} current={cur} />}
                {s.graph && <GraphPanel graph={s.graph} />}
              </div>
            )}

            {tab === "dashboard" && s.profile && <Dashboard profile={s.profile} />}
            {tab === "dashboard" && !s.profile && (
              <p className="text-sm text-zinc-600">Answer a check question to populate the profile.</p>
            )}
          </div>

          {/* side rail */}
          <aside className="space-y-4">
            <div className="rounded-xl border border-edge bg-panel p-4">
              <h3 className="mb-2 text-xs uppercase tracking-widest text-zinc-500">Controls</h3>
              <div className="flex gap-2">
                <button onClick={s.next} disabled={s.busy || !!s.question}
                  className="flex-1 rounded-lg bg-accent2 py-2 text-xs font-semibold text-black disabled:opacity-40">
                  next concept
                </button>
                <button onClick={() => setAuto(!auto)}
                  className={`rounded-lg border px-3 py-2 text-xs ${auto
                    ? "border-accent text-accent" : "border-edge text-zinc-400"}`}>
                  auto
                </button>
              </div>
            </div>

            <div className="rounded-xl border border-edge bg-panel p-4">
              <h3 className="mb-2 text-xs uppercase tracking-widest text-zinc-500">
                Interrupt & ask
              </h3>
              <div className="flex gap-2">
                <input value={ask} onChange={(e) => setAsk(e.target.value)}
                  onKeyDown={async (e) => {
                    if (e.key === "Enter" && ask.trim()) {
                      const r = await s.ask(ask); if (r) setAsked({ q: ask, a: r.answer }); setAsk("");
                    }
                  }}
                  placeholder="ask the teacher…"
                  className="flex-1 rounded-lg border border-edge bg-black/40 px-2 py-1.5 text-xs" />
              </div>
              {asked && (
                <div className="mt-3 rounded-lg border border-edge p-2 text-xs">
                  <p className="text-zinc-500">{asked.q}</p>
                  <p className="mt-1 text-zinc-300">{asked.a}</p>
                </div>
              )}
            </div>

            <div className="rounded-xl border border-edge bg-panel p-4">
              <h3 className="mb-2 text-xs uppercase tracking-widest text-zinc-500">Agent trace</h3>
              <div className="max-h-72 space-y-1 overflow-y-auto font-mono text-[10px] text-zinc-500">
                {s.log.map((l, i) => <div key={i}>{l}</div>)}
              </div>
            </div>
          </aside>
        </div>
      )}
    </main>
  );
}

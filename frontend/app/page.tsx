"use client";
import { useEffect, useState } from "react";
import { useSession } from "@/lib/useSession";
import { Lesson } from "@/components/Lesson";
import { Dashboard, GraphPanel, PlanPanel, QuestionCard, ReportCard } from "@/components/Panels";
import { Setup } from "@/components/Setup";
import type { LanguageOption } from "@/lib/types";

type Tab = "lesson" | "plan" | "dashboard";

export default function Home() {
  const s = useSession();
  const [tab, setTab] = useState<Tab>("lesson");
  const [langs, setLangs] = useState<LanguageOption[]>([]);
  const [auto, setAuto] = useState(true);
  const [ask, setAsk] = useState("");
  const [asked, setAsked] = useState<{ q: string; a: string } | null>(null);
  const [caps, setCaps] = useState<any>(null);

  useEffect(() => {
    fetch("/api/health").then((r) => r.json()).then(setCaps).catch(() => {});
    fetch("/api/languages").then((r) => r.json())
      .then((d) => setLangs(d.languages)).catch(() => {});
  }, []);

  const begin = async (input: { file?: File | null; topic?: string }, learner: any) => {
    const sid = await s.start(input, learner);
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
          {s.graph && (
            <span className="rounded-full border border-edge px-2 py-1 text-zinc-500">
              {s.graph.source} · {s.graph.subject} · {s.language}
            </span>
          )}
          {caps && (
            <span className="rounded-full border border-edge px-2 py-1 text-zinc-500">
              llm {caps.capabilities.llm ? "on" : "local"} · tts{" "}
              {caps.capabilities.tts ? "on" : "sim"} · avatar {caps.capabilities.avatar_mode}
            </span>
          )}
        </div>
      </header>

      {/* setup */}
      {!s.sessionId && <Setup onStart={begin} busy={s.busy} />}

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

            {tab === "dashboard" && (
              <div className="space-y-4">
                {s.report && <ReportCard report={s.report} />}
                {s.profile && <Dashboard profile={s.profile} />}
              </div>
            )}
            {tab === "dashboard" && !s.profile && !s.report && (
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
                Teaching language
              </h3>
              <select value={s.language}
                onChange={(e) => s.switchLanguage(e.target.value)}
                className="w-full rounded-lg border border-edge bg-black/40 px-2 py-1.5 text-xs">
                {(langs.length ? langs : [{ code: "en", name: "English", native: "English" }])
                  .map((l) => <option key={l.code} value={l.code}>{l.name} — {l.native}</option>)}
              </select>
              <p className="mt-1 text-[10px] text-zinc-600">
                switches mid-lesson; progress is preserved
              </p>
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

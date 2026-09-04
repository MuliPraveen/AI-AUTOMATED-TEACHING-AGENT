"use client";
/**
 * The lesson stage: avatar + playback clock + caption highlighting + the
 * interactive canvas whose blocks reveal exactly at their narration cue points.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Avatar } from "./Avatar";
import { BlockView } from "./Blocks";
import type { TeachingTurn } from "@/lib/types";

export function Lesson({ turn, onDone }: { turn: TeachingTurn; onDone?: () => void }) {
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(true);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const rafRef = useRef(0);
  const startedAt = useRef(0);

  const duration = turn.audio.duration || 1;

  /* ---------------------------------------------------------- clock ----- */
  useEffect(() => {
    setTime(0); setPlaying(true); startedAt.current = performance.now();
    const tick = () => {
      const t = audioRef.current && !audioRef.current.paused
        ? audioRef.current.currentTime
        : (performance.now() - startedAt.current) / 1000;
      setTime(t);
      if (t >= duration) { setPlaying(false); onDone?.(); return; }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turn.concept_id, turn.narration]);

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {}, 1000);
    return () => clearInterval(t);
  }, [playing]);

  /* --------------------------------- narration char position at time t --- */
  const charAt = useMemo(() => {
    const T = turn.audio.timings;
    if (!T.length) return turn.narration.length;
    let lo = 0, hi = T.length - 1, best = 0;
    while (lo <= hi) {                       // binary search on the timing track
      const mid = (lo + hi) >> 1;
      if (T[mid].start <= time) { best = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return T[best].char + T[best].word.length;
  }, [time, turn]);

  const visible = turn.blocks.filter((b) => b.cue_at_char <= charAt);
  const pct = Math.min(100, (time / duration) * 100);

  const replay = () => {
    setTime(0); startedAt.current = performance.now(); setPlaying(true);
    if (audioRef.current) { audioRef.current.currentTime = 0; audioRef.current.play(); }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
      {/* avatar column */}
      <div className="space-y-3">
        <div className="aspect-square overflow-hidden rounded-xl border border-edge bg-panel">
          <Avatar visemes={turn.audio.visemes} time={time} speaking={playing}
                  videoUrl={turn.avatar?.video_url} />
        </div>
        {turn.audio.audio_url && (
          <audio ref={audioRef} src={turn.audio.audio_url} autoPlay
                 onEnded={() => { setPlaying(false); onDone?.(); }} className="w-full" controls />
        )}
        <div className="rounded-xl border border-edge bg-panel p-3">
          <div className="flex items-baseline justify-between text-xs text-zinc-500">
            <span className="uppercase tracking-widest">{turn.depth}</span>
            <span>{turn.progress.index}/{turn.progress.total} · {turn.minutes}m</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-edge">
            <div className="h-full bg-accent transition-[width] duration-200" style={{ width: `${pct}%` }} />
          </div>
          <div className="mt-2 flex gap-2">
            <button onClick={replay}
              className="rounded-md border border-edge px-2 py-1 text-xs hover:border-accent">
              replay
            </button>
            <button onClick={() => { setTime(duration); setPlaying(false); onDone?.(); }}
              className="rounded-md border border-edge px-2 py-1 text-xs hover:border-accent">
              skip
            </button>
          </div>
        </div>
      </div>

      {/* canvas column */}
      <div className="space-y-4">
        <div>
          <h2 className="text-xl font-semibold text-accent">{turn.concept}</h2>
        </div>
        <div className="rounded-xl border border-edge bg-panel p-4 leading-relaxed">
          <span className="text-zinc-100">{turn.narration.slice(0, charAt)}</span>
          <span className="text-zinc-600">{turn.narration.slice(charAt)}</span>
        </div>
        <div className="space-y-3">
          {visible.map((b, i) => <BlockView key={i} block={b} />)}
          {!visible.length && (
            <div className="rounded-xl border border-dashed border-edge p-8 text-center text-sm text-zinc-600">
              visuals appear in sync with the narration…
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

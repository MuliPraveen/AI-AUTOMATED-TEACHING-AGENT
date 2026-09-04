"use client";
/**
 * Viseme-driven canvas avatar. When the backend returns a real talking-head
 * video (HeyGen / LivePortrait) we play that instead; otherwise this rig
 * animates from the viseme track so the mouth always matches the audio clock.
 */
import { useEffect, useRef } from "react";
import type { Viseme } from "@/lib/types";

const MOUTH: Record<string, { w: number; h: number }> = {
  AI: { w: 34, h: 26 }, E: { w: 40, h: 14 }, O: { w: 24, h: 28 }, U: { w: 18, h: 20 },
  MBP: { w: 30, h: 3 }, FV: { w: 32, h: 9 }, L: { w: 28, h: 18 }, rest: { w: 26, h: 5 },
};

export function Avatar({
  visemes, time, speaking, videoUrl,
}: { visemes: Viseme[]; time: number; speaking: boolean; videoUrl?: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const shape = useRef("rest");
  const idx = useRef(0);

  // Advance the viseme pointer monotonically (O(1) per frame).
  useEffect(() => {
    if (!speaking) { shape.current = "rest"; idx.current = 0; return; }
    while (idx.current < visemes.length && visemes[idx.current].t <= time) {
      shape.current = visemes[idx.current].shape; idx.current++;
    }
    if (idx.current > 0 && visemes[idx.current - 1]?.t > time) idx.current = 0;
  }, [time, visemes, speaking]);

  useEffect(() => {
    const c = canvas.current; if (!c) return;
    const ctx = c.getContext("2d")!;
    let raf = 0, t0 = performance.now();
    const draw = () => {
      const t = (performance.now() - t0) / 1000;
      const W = c.width, H = c.height;
      ctx.clearRect(0, 0, W, H);
      const g = ctx.createRadialGradient(W / 2, H * 0.45, 20, W / 2, H * 0.5, W * 0.7);
      g.addColorStop(0, "#1b2030"); g.addColorStop(1, "#0a0a0b");
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

      const cx = W / 2, cy = H * 0.5 + Math.sin(t * 1.1) * 2;
      // head
      ctx.fillStyle = "#e8c9a8";
      ctx.beginPath(); ctx.ellipse(cx, cy, 78, 96, 0, 0, Math.PI * 2); ctx.fill();
      // hair
      ctx.fillStyle = "#2c2f3a";
      ctx.beginPath(); ctx.ellipse(cx, cy - 62, 80, 46, 0, Math.PI, 0); ctx.fill();
      // eyes (blink every ~4s)
      const blink = t % 4.2 < 0.14;
      ctx.fillStyle = "#ffffff";
      for (const dx of [-30, 30]) {
        ctx.beginPath();
        ctx.ellipse(cx + dx, cy - 18, 14, blink ? 1.5 : 9, 0, 0, Math.PI * 2); ctx.fill();
      }
      if (!blink) {
        ctx.fillStyle = "#2b3a55";
        for (const dx of [-30, 30]) {
          ctx.beginPath();
          ctx.arc(cx + dx + Math.sin(t * 0.6) * 2, cy - 17, 5, 0, Math.PI * 2); ctx.fill();
        }
      }
      // brows
      ctx.strokeStyle = "#2c2f3a"; ctx.lineWidth = 4; ctx.lineCap = "round";
      for (const dx of [-30, 30]) {
        ctx.beginPath();
        ctx.moveTo(cx + dx - 15, cy - 38); ctx.lineTo(cx + dx + 15, cy - 41 - (speaking ? 2 : 0));
        ctx.stroke();
      }
      // nose
      ctx.strokeStyle = "#c9a684";
      ctx.beginPath(); ctx.moveTo(cx, cy - 6); ctx.lineTo(cx - 6, cy + 14);
      ctx.lineTo(cx + 3, cy + 15); ctx.stroke();
      // mouth from viseme
      const m = MOUTH[shape.current] ?? MOUTH.rest;
      ctx.fillStyle = "#7a2f38";
      ctx.beginPath(); ctx.ellipse(cx, cy + 46, m.w / 2, Math.max(m.h / 2, 1.5), 0, 0, Math.PI * 2);
      ctx.fill();
      if (m.h > 12) {
        ctx.fillStyle = "#fff";
        ctx.beginPath();
        ctx.ellipse(cx, cy + 46 - m.h / 4, m.w / 2 - 4, 3, 0, 0, Math.PI * 2); ctx.fill();
      }
      // shoulders
      ctx.fillStyle = "#3b4358";
      ctx.beginPath(); ctx.ellipse(cx, H + 34, 118, 74, 0, 0, Math.PI * 2); ctx.fill();

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [speaking]);

  if (videoUrl) {
    return <video src={videoUrl} autoPlay playsInline className="h-full w-full rounded-xl object-cover" />;
  }
  return (
    <div className="relative h-full w-full">
      <canvas ref={canvas} width={360} height={330} className="h-full w-full rounded-xl" />
      <div className="absolute left-3 top-3 flex items-center gap-2 rounded-full bg-black/60 px-2.5 py-1 text-[10px] uppercase tracking-widest">
        <span className={`h-1.5 w-1.5 rounded-full ${speaking ? "animate-pulse bg-accent" : "bg-zinc-600"}`} />
        {speaking ? "teaching" : "idle"}
      </div>
    </div>
  );
}

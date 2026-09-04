"use client";
import { useEffect, useRef, useState } from "react";
import katex from "katex";
import type { VisualBlock } from "@/lib/types";

/* ------------------------------------------------------------------ LaTeX */
export function Latex({ src }: { src: string }) {
  const [html, setHtml] = useState("");
  useEffect(() => {
    try {
      setHtml(katex.renderToString(src.replace(/^\$+|\$+$/g, ""), {
        displayMode: true, throwOnError: false, output: "html",
      }));
    } catch { setHtml(`<pre>${src}</pre>`); }
  }, [src]);
  return <div className="overflow-x-auto py-2 text-lg" dangerouslySetInnerHTML={{ __html: html }} />;
}

/* ---------------------------------------------------------------- Mermaid */
let mermaidReady: Promise<any> | null = null;
function loadMermaid() {
  if (!mermaidReady) {
    mermaidReady = import("mermaid").then((m) => {
      m.default.initialize({
        startOnLoad: false, theme: "dark", securityLevel: "loose",
        themeVariables: { primaryColor: "#1f2937", lineColor: "#6ee7b7", fontSize: "14px" },
      });
      return m.default;
    });
  }
  return mermaidReady;
}

export function Mermaid({ src }: { src: string }) {
  const [svg, setSvg] = useState("");
  const id = useRef(`m${Math.random().toString(36).slice(2)}`);
  useEffect(() => {
    let alive = true;
    loadMermaid()
      .then((m) => m.render(id.current, src))
      .then((r: any) => alive && setSvg(r.svg))
      .catch(() => alive && setSvg(`<pre class="text-xs text-red-400">${src}</pre>`));
    return () => { alive = false; };
  }, [src]);
  return <div className="flex justify-center py-2 [&_svg]:max-w-full" dangerouslySetInnerHTML={{ __html: svg }} />;
}

/* ------------------------------------------------------------------- Code */
const KEYWORDS =
  /\b(def|class|return|if|elif|else|for|while|import|from|as|with|try|except|lambda|yield|async|await|const|let|var|function|new|this|export|in|not|and|or|None|True|False|null|true|false)\b/g;

export function Code({ src, language }: { src: string; language: string }) {
  const html = src
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/(#.*$|\/\/.*$)/gm, '<span class="text-zinc-500">$1</span>')
    .replace(/('[^']*'|"[^"]*")/g, '<span class="text-amber-300">$1</span>')
    .replace(KEYWORDS, '<span class="text-indigo-300">$1</span>')
    .replace(/\b(\d+\.?\d*)\b/g, '<span class="text-emerald-300">$1</span>');
  return (
    <div className="rounded-lg border border-edge bg-black/50">
      <div className="border-b border-edge px-3 py-1 font-mono text-[10px] uppercase tracking-widest text-zinc-500">
        {language}
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-[13px] leading-relaxed"
           dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}

/* --------------------------------------------------------------- Renderer */
export function BlockView({ block }: { block: VisualBlock }) {
  return (
    <div className="animate-[fadeIn_.4s_ease] rounded-xl border border-edge bg-panel p-4">
      {block.type === "latex" && <Latex src={block.content} />}
      {block.type === "mermaid" && <Mermaid src={block.content} />}
      {block.type === "code" && <Code src={block.content} language={block.language} />}
      {block.type === "text" && <p className="text-sm text-zinc-300">{block.content}</p>}
      {block.type === "image" && <img src={block.content} alt={block.caption} className="rounded-lg" />}
      {block.caption && <div className="mt-2 text-xs text-zinc-500">{block.caption}</div>}
    </div>
  );
}

"use client";
/**
 * Single source of truth for the lesson: owns the WebSocket, the FSM mirror and
 * the playback clock. Components stay dumb and render from this state.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  Evaluation, KnowledgeGraph, LessonPlan, Question, StudentProfile, TeachingTurn, WSEvent,
} from "./types";

export function useSession() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [state, setState] = useState("idle");
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [plan, setPlan] = useState<LessonPlan | null>(null);
  const [turn, setTurn] = useState<TeachingTurn | null>(null);
  const [question, setQuestion] = useState<Question | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [quiz, setQuiz] = useState<Question[]>([]);
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const ws = useRef<WebSocket | null>(null);

  const push = (m: string) =>
    setLog((l) => [`${new Date().toLocaleTimeString()}  ${m}`, ...l].slice(0, 60));

  /* ------------------------------------------------------------ socket -- */
  const connect = useCallback((sid: string) => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${proto}://${location.host}/api/ws/${sid}`);
    socket.onmessage = (e) => {
      const ev: WSEvent = JSON.parse(e.data);
      switch (ev.type) {
        case "state": setState(ev.payload.state); break;
        case "knowledge_graph": setGraph(ev.payload.graph); push(`knowledge graph: ${ev.payload.graph.concepts.length} concepts`); break;
        case "lesson_plan": setPlan(ev.payload.plan); push("lesson plan allocated"); break;
        case "teaching_turn":
          setTurn(ev.payload as TeachingTurn); setQuestion(null); setEvaluation(null);
          push(`teaching: ${ev.payload.concept} (${ev.payload.depth})`); break;
        case "question": setQuestion(ev.payload.question); push("check for understanding"); break;
        case "evaluation":
          setEvaluation(ev.payload.evaluation); setProfile(ev.payload.profile);
          push(ev.payload.evaluation.correct ? "correct" :
            `misconception: ${ev.payload.evaluation.misconception ?? "unknown"}`); break;
        case "answer": push(`answered student question`); break;
        case "session_complete":
          setProfile(ev.payload.profile); setQuiz(ev.payload.quiz);
          push("session complete"); break;
      }
    };
    socket.onopen = () => push("live channel connected");
    socket.onclose = () => push("live channel closed");
    ws.current = socket;
  }, []);

  useEffect(() => () => ws.current?.close(), []);

  /* ------------------------------------------------------------- actions */
  const start = useCallback(async (file: File, minutes: number) => {
    setBusy(true);
    try {
      const r = await fetch("/api/sessions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minutes }),
      });
      const { session_id } = await r.json();
      setSessionId(session_id);
      connect(session_id);
      await new Promise((res) => setTimeout(res, 250)); // let WS attach
      const fd = new FormData();
      fd.append("file", file);
      fd.append("minutes", String(minutes));
      const ing = await fetch(`/api/sessions/${session_id}/ingest`, { method: "POST", body: fd });
      if (!ing.ok) throw new Error((await ing.json()).detail ?? "ingest failed");
      const data = await ing.json();
      setGraph(data.graph); setPlan(data.plan);
      return session_id;
    } catch (e: any) {
      push(`error: ${e.message}`);
      return null;
    } finally { setBusy(false); }
  }, [connect]);

  const next = useCallback(async () => {
    if (!sessionId) return;
    setBusy(true);
    try {
      const r = await fetch(`/api/sessions/${sessionId}/next`, { method: "POST" });
      const d = await r.json();
      if (!d.done) setTurn(d);
    } finally { setBusy(false); }
  }, [sessionId]);

  const answer = useCallback(async (a: string | number) => {
    if (!sessionId) return;
    setBusy(true);
    try {
      const r = await fetch(`/api/sessions/${sessionId}/answer`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer: a }),
      });
      const d = await r.json();
      setEvaluation(d.evaluation); setProfile(d.profile); setQuestion(null);
    } finally { setBusy(false); }
  }, [sessionId]);

  const ask = useCallback(async (q: string) => {
    if (!sessionId) return null;
    const r = await fetch(`/api/sessions/${sessionId}/ask`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q }),
    });
    return r.ok ? await r.json() : null;
  }, [sessionId]);

  return {
    sessionId, state, graph, plan, turn, question, evaluation, profile, quiz, log, busy,
    start, next, answer, ask,
  };
}

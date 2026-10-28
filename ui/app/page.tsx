"use client";

import { useEffect, useRef, useState } from "react";
import Chat, { ChatMsg } from "../components/Chat";
import GraphView from "../components/GraphView";
import PendingStrip from "../components/PendingStrip";
import Timeline, { StreamEvent } from "../components/Timeline";
import TottieFace, { FaceState } from "../components/TottieFace";

export default function Home() {
  const [session] = useState(
    () => `ui-${Math.random().toString(36).slice(2, 8)}`
  );
  const [memory, setMemory] = useState(true);
  const [tab, setTab] = useState<"timeline" | "graph">("timeline");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [path, setPath] = useState<string[]>([]);
  const [face, setFace] = useState<FaceState>("idle");
  const [busy, setBusy] = useState(false);
  const [graphTick, setGraphTick] = useState(0);
  const faceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flash = (s: FaceState, ms = 2200) => {
    setFace(s);
    if (faceTimer.current) clearTimeout(faceTimer.current);
    faceTimer.current = setTimeout(() => setFace("idle"), ms);
  };

  useEffect(() => {
    const src = new EventSource(`/api/events?session_id=${session}`);
    src.onmessage = (m) => {
      try {
        const e = JSON.parse(m.data) as StreamEvent;
        setEvents((xs) => [e, ...xs].slice(0, 100));
        if (e.action && (e.action.op === "NEW" || e.action.op === "SUPERSEDE")) {
          setGraphTick((n) => n + 1);
          flash("remembering");
        }
      } catch {
        /* ping frames carry no data */
      }
    };
    return () => src.close();
  }, [session]);

  const send = async (text: string) => {
    setMessages((xs) => [...xs, { role: "user", text }]);
    setBusy(true);
    setFace("thinking");
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, session_id: session, memory }),
      });
      const j = await r.json();
      setMessages((xs) => [
        ...xs,
        {
          role: "tottie",
          text: j.reply ?? "(no reply)",
          card: j.card ?? null,
          confidence: j.confidence,
          abstain: j.abstain,
        },
      ]);
      setPath(j.path ?? []);
      flash("speaking");
    } catch {
      setMessages((xs) => [...xs, { role: "tottie", text: "(core unreachable)" }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="h-screen max-w-[1440px] mx-auto flex flex-col px-4 py-3 gap-3">
      <header className="flex items-center gap-3">
        <TottieFace state={face} />
        <div className="flex-1">
          <h1 className="text-lg font-semibold leading-tight">Tottie</h1>
          <p className="dim text-xs mono">session {session} · live memory</p>
        </div>
        <button
          className="action text-sm"
          onClick={() => setMemory((m) => !m)}
          title="ON: recall + store every turn. OFF: raw model, nothing stored."
        >
          memory {memory ? "ON" : "OFF"}
        </button>
        <button
          className="action text-sm"
          disabled
          title="Consolidation lands in W5 — this button sleeps then."
        >
          sleep
        </button>
      </header>
      {!memory && (
        <p className="text-xs dim card px-3 py-1">
          ablation OFF — raw model: no recall, no writes. Flip ON to feel the
          difference.
        </p>
      )}
      <PendingStrip refreshKey={graphTick} />
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[11fr_9fr] gap-3 min-h-0">
        <section className="card p-3 min-h-0 flex flex-col">
          <Chat messages={messages} onSend={send} busy={busy} />
        </section>
        <section className="card p-3 min-h-0 flex flex-col">
          <div className="flex gap-2 mb-2">
            {(["timeline", "graph"] as const).map((t) => (
              <button
                key={t}
                className="action text-sm"
                disabled={tab === t}
                onClick={() => setTab(t)}
              >
                {t === "timeline" ? "Timeline" : "3D brain"}
              </button>
            ))}
          </div>
          <div className="flex-1 min-h-0 overflow-hidden">
            {tab === "timeline" ? (
              <Timeline events={events} />
            ) : (
              <GraphView path={path} fresh={graphTick} />
            )}
          </div>
        </section>
      </div>
    </main>
  );
}

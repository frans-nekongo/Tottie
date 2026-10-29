"use client";

import { useEffect, useRef, useState } from "react";
import GraphView from "../components/GraphView";
import PendingStrip from "../components/PendingStrip";
import Timeline, { StreamEvent } from "../components/Timeline";
import TottieFace, { FaceState } from "../components/TottieFace";

// Agent observatory: no chat here — this view watches memories form as
// agents work. Timeline streams every memory event live; the 3D brain
// shows the nodes and links those events create.
export default function Home() {
  const [session, setSession] = useState("");
  useEffect(() => {
    // Client-only: Math.random / location in useState break SSR hydration
    // (React #418: server HTML must match the first client render).
    setSession(`ui-${Math.random().toString(36).slice(2, 8)}`);
    if (new URLSearchParams(window.location.search).get("tab") === "graph") {
      setTab("graph");
    }
  }, []);
  const [tab, setTab] = useState<"timeline" | "graph">("timeline");
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [face, setFace] = useState<FaceState>("idle");
  const [sleeping, setSleeping] = useState(false);
  const [sleepNote, setSleepNote] = useState<string | null>(null);
  const [graphTick, setGraphTick] = useState(0);
  const faceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flash = (s: FaceState, ms = 2200) => {
    setFace(s);
    if (faceTimer.current) clearTimeout(faceTimer.current);
    faceTimer.current = setTimeout(() => setFace("idle"), ms);
  };

  useEffect(() => {
    if (!session) return;
    if (new URLSearchParams(window.location.search).get("stream") === "off") {
      return; // headless gates / stills: no infinite stream to settle
    }
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

  return (
    <main className="h-screen max-w-[1440px] mx-auto flex flex-col px-4 py-3 gap-3">
      <header className="flex items-center gap-3">
        <TottieFace state={face} />
        <div className="flex-1">
          <h1 className="text-lg font-semibold leading-tight">Tottie</h1>
          <p className="dim text-xs mono">session {session} · agent observatory</p>
        </div>
        <button
          className="action text-sm"
          disabled={sleeping || !session}
          title="Run Sleep: replay episodes into semantic knowledge."
          onClick={async () => {
            setSleeping(true);
            setFace("remembering");
            setSleepNote("replaying…");
            try {
              const r = await fetch("/api/sleep", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: session }),
              });
              const j = await r.json();
              setSleepNote(
                `${j.episodes_replayed ?? 0} episodic → ` +
                  `${j.semantic_written ?? 0} semantic; ` +
                  `${j.ranked_out ?? 0} ranked out` +
                  (j.semantic_error ? ` (semanticise: ${j.semantic_error})` : "")
              );
              setGraphTick((n) => n + 1);
            } catch {
              setSleepNote("(core unreachable)");
            } finally {
              setSleeping(false);
              setFace("idle");
            }
          }}
        >
          {sleeping ? "sleeping…" : "sleep"}
        </button>
        {sleepNote && <p className="text-xs dim mono">{sleepNote}</p>}
      </header>
      <PendingStrip refreshKey={graphTick} />
      <div className="flex-1 min-h-0 flex flex-col card p-3">
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
            <GraphView path={[]} fresh={graphTick} />
          )}
        </div>
      </div>
    </main>
  );
}

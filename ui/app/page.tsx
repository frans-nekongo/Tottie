"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import AgentsView from "../components/AgentsView";
import BirthFeed, { FeedItem } from "../components/BirthFeed";
import GraphView from "../components/GraphView";
import PendingStrip from "../components/PendingStrip";
import type { StreamEvent } from "../components/Timeline";
import TottieFace, { FaceState } from "../components/TottieFace";

// Agent observatory: no chat here — this view watches memories form as
// agents work. The agents board shows who is visible/paired (bluetooth);
// the 3D brain shows the nodes and links their memories create. The event
// stream still runs underneath to wake the graph and the face.
export default function Home() {
  const [session, setSession] = useState("");
  // Watch target: ?owner= narrows the owner (default owner_local),
  // ?session= narrows one session (default: all sessions stream).
  const [watchOwner, setWatchOwner] = useState("owner_local");
  const [watchSession, setWatchSession] = useState("");
  useEffect(() => {
    // Client-only: Math.random / location in useState break SSR hydration
    // (React #418: server HTML must match the first client render).
    setSession(`ui-${Math.random().toString(36).slice(2, 8)}`);
    const q = new URLSearchParams(window.location.search);
    if (q.get("tab") === "agents") {
      setTab("agents");
    } else if (q.get("tab") === "graph") {
      setTab("graph");
    }
    if (q.get("owner")) setWatchOwner(q.get("owner")!);
    if (q.get("session")) setWatchSession(q.get("session")!);
  }, []);
  const [tab, setTab] = useState<"agents" | "graph">("graph");
  const [face, setFace] = useState<FaceState>("idle");
  const [sleeping, setSleeping] = useState(false);
  const [sleepNote, setSleepNote] = useState<string | null>(null);
  const [graphTick, setGraphTick] = useState(0);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [live, setLive] = useState(false);
  const [syncMs, setSyncMs] = useState<number | null>(null);
  const faceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const feedKey = useRef(0);
  // The brain gates the fanfare: notifications/flashes wait until the
  // graph has adopted its first data (no births announced over a
  // "growing the brain" placeholder). Ticks still flow pre-ready so the
  // graph itself catches up.
  const graphReadyRef = useRef(false);
  const markGraphReady = useCallback(() => {
    graphReadyRef.current = true;
  }, []);
  useEffect(() => {
    graphReadyRef.current = false;
  }, [watchOwner]);
  const onSync = useCallback((ms: number) => setSyncMs(ms), []);

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
    const q = new URLSearchParams({ owner: watchOwner });
    if (watchSession) q.set("session_id", watchSession);
    const src = new EventSource(`/api/events?${q.toString()}`);
    // Core emits NAMED `event: memory` frames: onmessage alone NEVER fires
    // for those (EventSource routes named events only to addEventListener).
    const onEvent = (m: MessageEvent) => {
      try {
        const e = JSON.parse(m.data) as StreamEvent;
        const a = e.action as Record<string, unknown> | null;
        const op = a?.op as string | undefined;
        if (!op) return; // ping frames carry no op
        // Every mutation refreshes the brain — including sweeps, whose
        // kills shrink out the instant they land, not on the next NEW.
        // Birth animation is clocked by GraphView at first paint.
        setGraphTick((n) => n + 1);
        if (!graphReadyRef.current) return;
        if (op === "NEW" || op === "SUPERSEDE") {
          flash("remembering");
          const text = (e.utterance ?? "").trim().slice(0, 110);
          if (text) {
            const key = ++feedKey.current;
            setFeed((f) => [{ key, op, text }, ...f].slice(0, 4));
          }
        }
      } catch {
        /* malformed frames never break the stream */
      }
    };
    src.onmessage = onEvent; // unnamed frames (defensive)
    src.addEventListener("memory", (ev) => onEvent(ev as MessageEvent));
    src.onopen = () => setLive(true);
    src.onerror = () => setLive(false);
    return () => src.close();
  }, [session, watchOwner, watchSession]);

  useEffect(() => {
    if (feed.length === 0) return;
    // 12s from the event: slow demo boxes paint seconds late.
    const to = setTimeout(() => setFeed([]), 12000);
    return () => clearTimeout(to);
  }, [feed]);

  return (
    <main className="h-screen max-w-[1440px] mx-auto flex flex-col px-4 py-3 gap-3">
      <header className="flex items-center gap-3">
        <TottieFace state={face} />
        <div className="flex-1">
          <h1 className="text-lg font-semibold leading-tight">
            Tottie{" "}
            <span
              className={live ? "livedot live" : "livedot"}
              title={live ? "stream live" : "stream reconnecting"}
            />
          </h1>
          <p className="dim text-xs mono">watching {watchOwner} · {watchSession || "all sessions"} · agent observatory · sync {syncMs === null ? "—" : `${syncMs}ms`}</p>
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
                body: JSON.stringify({ owner: watchOwner, session_id: watchSession || session }),
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
      <PendingStrip refreshKey={graphTick} owner={watchOwner} />
      <div className="flex-1 min-h-0 flex flex-col card p-3 relative">
        <div className="absolute top-3 right-3 z-10">
          <BirthFeed items={feed} />
        </div>
        <div className="flex gap-2 mb-2">
          {(["agents", "graph"] as const).map((t) => (
            <button
              key={t}
              className="action text-sm"
              disabled={tab === t}
              onClick={() => setTab(t)}
            >
              {t === "agents" ? "Agents" : "3D brain"}
            </button>
          ))}
        </div>
        <div className="flex-1 min-h-0 overflow-hidden">
          {tab === "agents" ? (
            <AgentsView owner={watchOwner} />
          ) : (
            <GraphView
              path={[]}
              fresh={graphTick}
              owner={watchOwner}
              onSync={onSync}
              onReady={markGraphReady}
            />
          )}
        </div>
      </div>
    </main>
  );
}

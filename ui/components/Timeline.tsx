"use client";

import { useEffect, useState } from "react";

export interface StreamEvent {
  id: number;
  ts: string;
  turn: number | null;
  utterance: string | null;
  verdict: Record<string, unknown> | null;
  action: Record<string, unknown> | null;
  cue: Record<string, unknown> | null;
  latency_ms: number | null;
  tokens: number | null;
}

interface Candidate {
  kind?: string;
  tier?: string;
  content?: string;
  tags?: string[];
}

function EventCard({ e }: { e: StreamEvent }) {
  const v = (e.verdict ?? {}) as Record<string, unknown>;
  const a = (e.action ?? {}) as Record<string, unknown>;
  const op = String(a.op ?? "?");
  const isRecall = op === "RECALL";
  const cands = (v.candidates as Candidate[] | undefined) ?? [];
  const [old, setOld] = useState<Record<string, string>>({});
  const sup = (a.superseded_ids as string[] | undefined) ?? [];
  useEffect(() => {
    sup.forEach((id) => {
      if (old[id] !== undefined) return;
      fetch(`/api/memories?id=${id}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((j) =>
          setOld((m) => ({ ...m, [id]: j?.memories?.[0]?.content ?? id.slice(0, 8) }))
        )
        .catch(() => setOld((m) => ({ ...m, [id]: id.slice(0, 8) })));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [e.id]);

  return (
    <div className="card px-3 py-2 text-sm">
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`chip op-${op}`}>{op}</span>
        {e.turn != null && <span className="dim mono text-xs">turn {e.turn}</span>}
        {e.latency_ms != null && (
          <span className="dim mono text-xs">{e.latency_ms}ms</span>
        )}
        {(e.cue?.type as string | undefined) && (
          <span className="chip">{String(e.cue?.type)}</span>
        )}
      </div>
      {e.utterance && <p className="mt-1">{e.utterance}</p>}
      {typeof v.reason === "string" && (
        <p className="dim mono text-xs mt-1">{v.reason}</p>
      )}
      {isRecall && (
        <p className="dim text-xs mt-1">
          confidence {String(v.confidence)}
          {v.abstain ? " · abstained — injected nothing" : ` · ${String(a.n)} hits injected`}
        </p>
      )}
      {cands.map((c, i) => (
        <div key={i} className="mt-1 text-xs">
          <span className="chip">{c.tier ?? ""}/{c.kind ?? ""}</span>{" "}
          <span>{c.content}</span>{" "}
          {(c.tags ?? []).map((t) => (
            <span key={t} className="dim mono text-xs">#{t} </span>
          ))}
        </div>
      ))}
      {sup.map((id) => (
        <p key={id} className="strike text-xs mt-1">
          superseded: {old[id] ?? id.slice(0, 8)}
        </p>
      ))}
    </div>
  );
}

export default function Timeline({ events }: { events: StreamEvent[] }) {
  if (events.length === 0)
    return <p className="dim text-sm">No steps yet — the stream lands here.</p>;
  return (
    <div className="space-y-2 overflow-y-auto pr-1">
      {events.map((e) => (
        <EventCard key={e.id} e={e} />
      ))}
    </div>
  );
}

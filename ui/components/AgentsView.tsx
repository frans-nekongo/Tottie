"use client";

import { useCallback, useEffect, useState } from "react";

type Agent = {
  id: string;
  label: string;
  transport: string;
  session_id: string | null;
  connected: boolean;
  online: boolean;
  last_seen: string;
};

function ago(iso: string): string {
  const s = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 1000));
  if (s < 5) return "now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

// Bluetooth board: agents announce themselves; the owner pairs chosen ones.
// Injection only serves paired agents.
export default function AgentsView({ owner }: { owner: string }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`/api/agents?owner=${owner}`);
      const j = await r.json();
      setAgents(j.agents ?? []);
      setErr(null);
    } catch {
      setErr("(core unreachable)");
    }
  }, [owner]);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  const toggle = async (a: Agent) => {
    setBusy(a.id);
    try {
      await fetch(`/api/agents/${a.connected ? "unpair" : "pair"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ owner, id: a.id }),
      });
      await load();
    } finally {
      setBusy(null);
    }
  };

  if (err) return <p className="dim mono text-sm p-2">{err}</p>;
  if (!agents.length)
    return (
      <p className="dim mono text-sm p-2">
        no agents visible — run `tottie register` or memory.register and it
        appears here
      </p>
    );
  return (
    <ul className="flex flex-col gap-2 overflow-y-auto h-full p-1">
      {agents.map((a) => (
        <li
          key={a.id}
          className="card p-2 flex items-center gap-3 text-sm"
        >
          <span
            title={a.online ? "online" : "offline"}
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: a.online ? "#4ade80" : "#52525b",
              flexShrink: 0,
            }}
          />
          <div className="flex-1 min-w-0">
            <div className="font-medium truncate">
              {a.label} <span className="dim mono">· {a.id}</span>
            </div>
            <div className="dim mono text-xs">
              {a.transport}
              {a.session_id ? ` · ${a.session_id}` : ""} · seen {ago(a.last_seen)}
            </div>
          </div>
          <span className="mono text-xs dim">
            {a.connected ? "paired" : "visible"}
          </span>
          <button
            className="action text-xs"
            disabled={busy === a.id}
            onClick={() => toggle(a)}
          >
            {busy === a.id ? "…" : a.connected ? "unpair" : "pair"}
          </button>
        </li>
      ))}
    </ul>
  );
}

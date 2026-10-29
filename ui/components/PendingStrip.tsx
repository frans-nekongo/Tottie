"use client";

import { useCallback, useEffect, useState } from "react";

interface Pending {
  id: string;
  content: string;
  kind: string;
  trust: string;
}

export default function PendingStrip({ refreshKey, owner }: { refreshKey: number; owner: string }) {
  const [rows, setRows] = useState<Pending[]>([]);
  const load = useCallback(() => {
    fetch(`/api/memories?quarantined=true&limit=20&owner=${encodeURIComponent(owner)}`)
      .then((r) => (r.ok ? r.json() : { memories: [] }))
      .then((j) => setRows(j.memories ?? []))
      .catch(() => setRows([]));
  }, [owner]);
  useEffect(load, [load, refreshKey]);

  const confirm = async (id: string) => {
    const r = await fetch("/api/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, owner }),
    });
    if (r.ok) setRows((xs) => xs.filter((x) => x.id !== id));
  };

  if (rows.length === 0) return null;
  return (
    <div className="card px-3 py-2">
      <p className="text-xs dim mb-1">
        pending — quarantined, visible, never injected ({rows.length})
      </p>
      <div className="space-y-1">
        {rows.map((r) => (
          <div key={r.id} className="flex items-center gap-2 text-sm">
            <span className="chip">{r.kind}</span>
            <span className="chip">{r.trust}</span>
            <span className="flex-1 truncate">{r.content}</span>
            <button className="action text-xs" onClick={() => confirm(r.id)}>
              confirm
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

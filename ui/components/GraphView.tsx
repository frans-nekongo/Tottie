"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import type { GraphLink, GraphNode } from "react-force-graph-3d";

const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), { ssr: false });

interface Node {
  id: string;
  label: string;
  tier: string;
  tags: string[];
  salience: number;
  quarantined: boolean;
  ranked_out?: boolean;
}
interface Link {
  source: string;
  target: string;
  relation: string;
  reason?: string;
}
interface Detail {
  content: string;
  tier: string;
  kind: string;
  tags: string[];
  salience: number;
}

const TIER_COLOR: Record<string, string> = {
  identity: "#d9a441",
  episodic: "#4cc3d9",
  knowledge: "#9a7bd0",
  procedural: "#6fbf73",
};

export default function GraphView({
  path,
  fresh,
  owner,
}: {
  path: string[];
  fresh: number; // bump to refetch after writes
  owner: string;
}) {
  const [data, setData] = useState<{ nodes: Node[]; links: Link[] } | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [area, setArea] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const pathSet = useRef<Set<string>>(new Set(path));
  pathSet.current = new Set(path);

  useEffect(() => {
    fetch(`/api/graph?owner=${encodeURIComponent(owner)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setData)
      .catch((e) => setErr(`graph unavailable (${e})`));
  }, [fresh, owner]);

  useEffect(() => {
    setArea(null);
    setDetail(null);
  }, [owner]);

  const pickArea = (slug: string | null) => {
    setArea(slug);
    setDetail(null);
  };

  const onNodeClick = useCallback((n: { id?: string }) => {
    if (!n.id) return;
    fetch(`/api/memories?id=${n.id}&owner=${encodeURIComponent(owner)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => setDetail(j?.memories?.[0] ?? null))
      .catch(() => setDetail(null));
  }, [owner]);

  if (err) return <p className="dim text-sm">{err}</p>;
  if (!data) return <p className="dim text-sm">growing the brain…</p>;
  const areaOf = (n: Node): string | null => {
    const t = (n.tags ?? []).find((x) => x.startsWith("area:"));
    return t ? t.slice(5) : null;
  };
  const areaCounts = new Map<string, number>();
  for (const n of data.nodes) {
    const a = areaOf(n);
    if (a) areaCounts.set(a, (areaCounts.get(a) ?? 0) + 1);
  }
  const areas = [...areaCounts.entries()].sort((x, y) => y[1] - x[1]);
  const visibleIds =
    area === null
      ? null
      : new Set(data.nodes.filter((n) => areaOf(n) === area).map((n) => n.id));
  const shownNodes = data.nodes.filter(
    (n) => visibleIds === null || visibleIds.has(n.id));
  const nodes = shownNodes.map((n) => {
    const onPath = pathSet.current.has(n.id);
    return {
      ...n,
      color: onPath
        ? "#ffffff"
        : n.quarantined || n.ranked_out
          ? "#5a5a66"
          : TIER_COLOR[n.tier] ?? "#e8e6e1",
      val: (1 + (n.salience ?? 0.5) * 3) * (onPath ? 1.8 : 1),
    };
  });
  const shownLinks = data.links.filter(
    (l) =>
      visibleIds === null ||
      (visibleIds.has(l.source) && visibleIds.has(l.target)));
  const links = shownLinks.map((l) => ({
    ...l,
    color:
      pathSet.current.has(l.source) && pathSet.current.has(l.target)
        ? "#ffffff"
        : l.relation === "supersedes"
          ? "#d9534f"
          : "rgba(160,160,175,0.35)",
  }));
  const endId = (e: string | GraphNode): string =>
    typeof e === "string" ? e : e.id;
  const onPath = (l: GraphLink): number =>
    pathSet.current.size > 0 &&
    pathSet.current.has(endId(l.source)) &&
    pathSet.current.has(endId(l.target))
      ? 3
      : 0;

  return (
    <div className="relative h-full min-h-[420px] flex flex-col">
      {areas.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 pb-2">
          <button
            className="action text-xs"
            disabled={area === null}
            onClick={() => pickArea(null)}
          >
            all
          </button>
          {areas.map(([slug, count]) => (
            <button
              key={slug}
              className="action text-xs"
              disabled={area === slug}
              onClick={() => pickArea(area === slug ? null : slug)}
              title={`${count} memories`}
            >
              {slug} <span className="dim mono">{count}</span>
            </button>
          ))}
          <span className="dim text-xs mono ml-auto">
            {shownNodes.length}/{data.nodes.length}
          </span>
        </div>
      )}
      <div className="relative flex-1 min-h-0">
      <ForceGraph3D
        graphData={{ nodes, links }}
        nodeLabel="label"
        nodeColor="color"
        nodeVal="val"
        linkColor="color"
        linkLabel="reason"
        linkWidth={1.2}
        linkDirectionalParticles={onPath}
        linkDirectionalParticleSpeed={0.006}
        linkDirectionalParticleColor={() => "#ffffff"}
        backgroundColor="#101014"
        showNavInfo={false}
        enableNodeDrag={true}
        onNodeClick={onNodeClick}
        cooldownTime={3000}
      />
      {detail && (
        <div className="card absolute bottom-2 left-2 right-2 px-3 py-2 text-xs">
          <button
            className="float-right dim"
            onClick={() => setDetail(null)}
            aria-label="close"
          >
            ×
          </button>
          <span className="chip">
            {detail.tier}/{detail.kind}
          </span>{" "}
          <span>{detail.content}</span>
          <div className="dim mono mt-1">
            sal {detail.salience?.toFixed(2)}{" "}
            {(detail.tags ?? []).map((t) => `#${t} `)}
          </div>
        </div>
      )}
      </div>
    </div>
  );
}

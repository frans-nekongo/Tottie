"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import type { FC, Ref } from "react";
import type ForceGraph3DHandle from "react-force-graph-3d";
import type {
  ForceGraph3DProps,
  GraphLink,
  GraphNode,
} from "react-force-graph-3d";

// dynamic()'s own types don't carry the imperative ref API, so restate the
// component type here. The kapsule runtime exposes its instance via ref;
// the headless pill-click probe proves the flight lands.
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
}) as unknown as FC<ForceGraph3DProps & { ref?: Ref<ForceGraph3DHandle> }>;

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
interface FGNode extends Node {
  color: string;
  val: number;
  x?: number;
  y?: number;
  z?: number;
  // Pinned coords for tombstones (the dying stay where they fell).
  fx?: number;
  fy?: number;
  fz?: number;
  // GraphNode carries an index signature; satisfy it explicitly.
  [key: string]: unknown;
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

const FRESH_MS = 2600; // white-hot drop-in window per newborn node
const DIE_MS = 700; // red shrink-out window per killed node

function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

function mixHex(a: string, b: string, t: number): string {
  // t=0 -> a, t=1 -> b; plain lerp, no deps
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return (
    "#" +
    pa
      .map((v, i) => Math.round(v + (pb[i] - v) * t).toString(16).padStart(2, "0"))
      .join("")
  );
}

function spawnOf(id: string): { x: number; y: number; z: number } {
  // Newborns spawn high above the cluster; the force layout pulls them
  // down into place — a literal drop-in. Deterministic scatter per id
  // so siblings don't stack.
  const h1 = hashStr(id);
  const h2 = hashStr(id + ":z");
  return { x: (h1 - 0.5) * 70, y: 130 + h1 * 50, z: (h2 - 0.5) * 70 };
}

export default function GraphView({
  path,
  fresh,
  owner,
  onSync,
}: {
  path: string[];
  fresh: number; // bump to refetch after writes
  owner: string;
  onSync?: (ms: number) => void; // fetch round-trip per refetch
}) {
  const [data, setData] = useState<{ nodes: Node[]; links: Link[] } | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [area, setArea] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [now, setNow] = useState(0); // animation clock, ticks while fresh
  const [burst, setBurst] = useState<{ ids: string[]; at: number } | null>(null);
  const pathSet = useRef<Set<string>>(new Set(path));
  pathSet.current = new Set(path);
  const bornAt = useRef(new Map<string, number>());
  const seenIds = useRef(new Set<string>());
  const painted = useRef(false); // first data adoptive, even when empty
  // Tombstones: id -> death time + last sim coords + size, for the red
  // shrink-out. prevNodes holds the node objects of the previous render
  // (the sim mutates them in place, so they carry live coords).
  const deadAt = useRef(
    new Map<string, { t: number; x: number; y: number; z: number; val: number }>()
  );
  const prevNodes = useRef(new Map<string, FGNode>());
  const burstIds = useRef<string[]>([]);
  const fgRef = useRef<ForceGraph3DHandle | null>(null);
  const reducedMotion = useRef(
    typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );

  useEffect(() => {
    const t0 = Date.now();
    fetch(`/api/graph?owner=${encodeURIComponent(owner)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        setData(d);
        onSync?.(Date.now() - t0);
      })
      .catch((e) => setErr(`graph unavailable (${e})`));
  }, [fresh, owner, onSync]);

  // Stamp births on the first frame that can actually paint them — not on
  // SSE arrival. Event-to-paint lag (refetch + a slow compositor) would
  // otherwise eat the drop-in window before a single frame shows it.
  // Deaths (superseded / swept rows the refetch no longer carries) become
  // tombstones: a red shrink-out at their last sim coords.
  useEffect(() => {
    if (!data) return;
    const t = Date.now();
    const live = new Set(data.nodes.map((n) => n.id));
    for (const [id, pn] of prevNodes.current) {
      if (!live.has(id) && !deadAt.current.has(id)) {
        deadAt.current.set(id, {
          t,
          x: pn.x ?? 0,
          y: pn.y ?? 0,
          z: pn.z ?? 0,
          val: pn.val ?? 2,
        });
      }
    }
    for (const [id, d] of deadAt.current) {
      if (t - d.t >= DIE_MS) deadAt.current.delete(id);
    }
    // Prune the dead so the maps never grow past the graph.
    for (const id of [...bornAt.current.keys()]) {
      if (!live.has(id)) bornAt.current.delete(id);
    }
    // The sim mutates these objects in place; their coords are fresh by
    // the time the next refetch diffs against them.
    prevNodes.current = new Map(
      nodes.filter((n) => !n.id.startsWith("dead:")).map((n) => [n.id, n])
    );
    if (!painted.current) {
      // First paint is not a birth: adopt silently, no flashes.
      painted.current = true;
      seenIds.current = live;
      return;
    }
    const fresh = data.nodes.filter((n) => !seenIds.current.has(n.id));
    if (fresh.length === 0) {
      seenIds.current = live;
      return;
    }
    const raf = requestAnimationFrame(() => {
      const rt = Date.now();
      const stamped: string[] = [];
      for (const n of fresh) {
        if (!seenIds.current.has(n.id)) {
          bornAt.current.set(n.id, rt);
          stamped.push(n.id);
        }
      }
      seenIds.current = live;
      if (stamped.length > 0) {
        burstIds.current = stamped;
        setBurst({ ids: stamped, at: rt });
        setNow(rt); // kick the animation clock + repaint
      }
    });
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  // Tick the animation clock only while newborns are cooling down or
  // tombstones are shrinking out.
  useEffect(() => {
    if (reducedMotion.current) return;
    const t = Date.now();
    let any = false;
    for (const b of bornAt.current.values()) {
      if (t - b < FRESH_MS) {
        any = true;
        break;
      }
    }
    if (!any) {
      for (const d of deadAt.current.values()) {
        if (t - d.t < DIE_MS) {
          any = true;
          break;
        }
      }
    }
    if (!any) return;
    const iv = setInterval(() => setNow(Date.now()), 120);
    return () => clearInterval(iv);
  }, [data, now]);

  useEffect(() => {
    if (!burst) return;
    // 9s: the demo narrator finishes the sentence before it leaves.
    const to = setTimeout(() => setBurst(null), 9000);
    return () => clearTimeout(to);
  }, [burst]);

  useEffect(() => {
    setArea(null);
    setDetail(null);
    setBurst(null);
    bornAt.current.clear();
    seenIds.current.clear();
    deadAt.current.clear();
    prevNodes.current.clear();
    burstIds.current = [];
    painted.current = false;
  }, [owner]);

  const pickArea = (slug: string | null) => {
    setArea(slug);
    setDetail(null);
  };

  const flyToNew = useCallback(() => {
    const ids = burstIds.current;
    if (ids.length === 0) return;
    burstIds.current = [];
    setBurst(null);
    pickArea(null); // newborns may hide behind the area filter
    // Frame the newborns' live centroid at a fixed friendly distance.
    // (zoomToFit on a lone newborn dives inside the sphere — verified.)
    const pts = ids.map((id) => {
      const pn = prevNodes.current.get(id);
      return pn?.x !== undefined && pn?.y !== undefined && pn?.z !== undefined
        ? { x: pn.x, y: pn.y, z: pn.z }
        : spawnOf(id);
    });
    const c = {
      x: pts.reduce((s, p) => s + p.x, 0) / pts.length,
      y: pts.reduce((s, p) => s + p.y, 0) / pts.length,
      z: pts.reduce((s, p) => s + p.z, 0) / pts.length,
    };
    let spread = 0;
    for (const p of pts) {
      spread = Math.max(
        spread,
        Math.hypot(p.x - c.x, p.y - c.y, p.z - c.z)
      );
    }
    const d = Math.min(600, Math.max(220, spread * 2.5 + 120));
    try {
      fgRef.current?.cameraPosition(
        { x: c.x, y: c.y + d * 0.25, z: c.z + d },
        c,
        800
      );
    } catch {
      /* graph not ready */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
  const clock = now || Date.now();
  const freshOf = (id: string): number => {
    // 1 = just born, 0 = cooled. Absent birth = long settled.
    if (reducedMotion.current) return 0;
    const b = bornAt.current.get(id);
    if (b === undefined) return 0;
    const age = clock - b;
    if (age < 0 || age >= FRESH_MS) return 0;
    return 1 - age / FRESH_MS;
  };
  const nodes = shownNodes.map((n) => {
    const onPath = pathSet.current.has(n.id);
    const heat = freshOf(n.id);
    const base = onPath
      ? "#ffffff"
      : n.quarantined || n.ranked_out
        ? "#5a5a66"
        : TIER_COLOR[n.tier] ?? "#e8e6e1";
    const node: FGNode = {
      ...n,
      color: heat > 0 ? mixHex("#ffffff", base, 1 - heat) : base,
      // Ease-out pop: violent shrink at first, gentle settle at the end.
      val: (1 + (n.salience ?? 0.5) * 3) * (onPath ? 1.8 : 1) *
        (1 + 1.2 * Math.pow(heat, 1.5)),
    };
    if (heat > 0.55) {
      const s = spawnOf(n.id);
      node.x = s.x;
      node.y = s.y;
      node.z = s.z;
    }
    return node;
  });
  const shownLinks = data.links.filter(
    (l) =>
      visibleIds === null ||
      (visibleIds.has(l.source) && visibleIds.has(l.target)));
  const links = shownLinks.map((l) => {
    const heat = Math.max(freshOf(l.source), freshOf(l.target));
    return {
      ...l,
      color:
        pathSet.current.has(l.source) && pathSet.current.has(l.target)
          ? "#ffffff"
          : heat > 0
            ? `rgba(255,255,255,${(0.25 + heat * 0.65).toFixed(2)})`
            : l.relation === "supersedes"
              ? "#d9534f"
              : "rgba(160,160,175,0.35)",
    };
  });
  // Tombstones: the killed shrink out red where they fell.
  const ghosts: FGNode[] = [];
  if (!reducedMotion.current) {
    for (const [id, d] of deadAt.current) {
      const p = 1 - (clock - d.t) / DIE_MS;
      if (p <= 0 || p > 1) continue;
      ghosts.push({
        id: `dead:${id}`,
        label: "",
        tier: "",
        tags: [],
        salience: 0,
        quarantined: false,
        color: "#d9534f",
        val: Math.max(0.15, d.val * p),
        x: d.x,
        y: d.y,
        z: d.z,
        fx: d.x,
        fy: d.y,
        fz: d.z,
      });
    }
  }
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
      {burst && burst.ids.length > 0 && (
        <button
          onClick={flyToNew}
          className="absolute top-2 left-1/2 -translate-x-1/2 z-10 card px-3 py-1 text-xs mono"
        >
          <span className="livedot live" /> {burst.ids.length} new — show me
        </button>
      )}
      <ForceGraph3D
        ref={fgRef}
        graphData={{ nodes: [...nodes, ...ghosts], links }}
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

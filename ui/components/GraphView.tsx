"use client";

import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import type ForceGraph3DHandle from "react-force-graph-3d";
import type { GraphLink, GraphNode } from "react-force-graph-3d";
import {
  baseDisplay,
  heatAt,
  linkBaseColor,
  linkGlowColor,
  mixHex,
  popScale,
  spawnOf,
} from "./graphMath";

// React.lazy, NOT next/dynamic: dynamic() swallows the imperative ref, which
// silently kills refresh(), camera flights, and zoomToFit — the graph renders
// but never animates and never frames. lazy preserves ref to the instance.
const ForceGraph3D = lazy(() => import("react-force-graph-3d"));

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
  // d3 fixed-position pins (birth hold + tombstones). The sim reads these
  // directly; null/undefined unpins.
  fx?: number;
  fy?: number;
  fz?: number;
  // Settled display. The rAF loop derives the animated color/val from this
  // plus heat; the render path never touches display except at rebuild.
  __base: { color: string; val: number };
  // GraphNode carries an index signature; satisfy it explicitly.
  [key: string]: unknown;
}
interface FGLink {
  // NOTE: d3-force swaps source/target for node object refs at runtime.
  // Read endpoints via endId(), never raw.
  source: string;
  target: string;
  relation: string;
  reason?: string;
  color: string;
  __base: string;
  [key: string]: unknown;
}
interface GraphCache {
  data: { nodes: Node[]; links: Link[] } | null;
  area: string | null;
  pathKey: string;
  struct: number;
  nodes: FGNode[];
  links: FGLink[];
  graphData: { nodes: FGNode[]; links: FGLink[] };
  byId: Map<string, FGNode>;
  linkByKey: Map<string, FGLink>;
}
interface Detail {
  content: string;
  tier: string;
  kind: string;
  tags: string[];
  salience: number;
}

const FRESH_MS = 3800; // bright electric birth drop-in window per newborn node
const DIE_MS = 700; // red shrink-out window per killed node
const BIRTH_COLOR = "#00f0ff"; // Vivid incandescent electric cyan

const endId = (e: string | GraphNode): string =>
  typeof e === "string" ? e : e.id;
const WHITE_PARTICLE = () => "#ffffff";

const emptyCache = (): GraphCache => ({
  data: null,
  area: null,
  pathKey: "",
  struct: -1,
  nodes: [],
  links: [],
  graphData: { nodes: [], links: [] },
  byId: new Map(),
  linkByKey: new Map(),
});

export default function GraphView({
  path,
  fresh,
  owner,
  onSync,
  onReady,
  birthGapMs = 550,
}: {
  path: string[];
  fresh: number; // bump to refetch after writes
  owner: string;
  onSync?: (ms: number) => void; // fetch round-trip per refetch
  onReady?: () => void; // first data adopted (or fetch settled): graph ready
  birthGapMs?: number; // stagger between sequential newborn adoptions
}) {
  const [data, setData] = useState<{ nodes: Node[]; links: Link[] } | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [area, setArea] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [burst, setBurst] = useState<{ ids: string[]; at: number } | null>(null);
  // Bumped only when graph membership changes (never per animation frame).
  const [struct, setStruct] = useState(0);
  const pathSet = useRef<Set<string>>(new Set(path));
  pathSet.current = new Set(path);
  const bornAt = useRef(new Map<string, number>());
  const seenIds = useRef(new Set<string>());
  const painted = useRef(false); // first data adoptive, even when empty
  const framed = useRef(false); // one zoomToFit per owner, after first paint
  // Tombstones: id -> death time + snapshot size. Coords live on the ghost
  // objects themselves (pinned via fx/fy/fz).
  const deadAt = useRef(
    new Map<string, { t: number; x: number; y: number; z: number; val: number }>()
  );
  // Node object pool with a STABLE graphData wrapper. kapsule compares props
  // by reference and reheats the whole sim to alpha=1 on every new identity,
  // so animation ticks must never rebuild this — the rAF loop mutates the
  // pooled objects in place and calls refresh() instead.
  const cache = useRef<GraphCache>(emptyCache());
  const loopRef = useRef(0);
  const burstIds = useRef<string[]>([]);
  // Sequential births: fresh ids queue here and pop one per birthGapMs —
  // each node appears and plays its drop-in before the next starts.
  const pendingRef = useRef<string[]>([]);
  const popTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;
  const fgRef = useRef<ForceGraph3DHandle | null>(null);
  const reducedMotion = useRef(
    typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );

  // Monotonic fetch generation: rapid `fresh` bumps overlap in flight,
  // and a stale response landing last would yank the brain backwards.
  const fetchSeq = useRef(0);
  useEffect(() => {
    const t0 = Date.now();
    const seq = ++fetchSeq.current;
    fetch(`/api/graph?owner=${encodeURIComponent(owner)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        if (seq !== fetchSeq.current) return; // superseded, drop it
        setData(d);
        onSync?.(Date.now() - t0);
      })
      .catch((e) => {
        if (seq !== fetchSeq.current) return;
        setErr(`graph unavailable (${e})`);
        onReadyRef.current?.(); // settled (failed): don't gate the feed forever
      });
  }, [fresh, owner, onSync]);

  // One animation frame: mutate pooled objects in place, repaint via
  // refresh(). No setState here — React never re-renders for animation,
  // so graphData keeps its identity and the sim is never reheated.
  const frame = useCallback(() => {
    loopRef.current = 0;
    const t = Date.now();
    const c = cache.current;
    let active = false;
    for (const [id, b] of bornAt.current) {
      const n = c.byId.get(id);
      if (!n) {
        bornAt.current.delete(id);
        continue;
      }
      const heat = heatAt(b, t, FRESH_MS);
      if (heat <= 0 || reducedMotion.current) {
        bornAt.current.delete(id);
        n.color = n.__base.color;
        n.val = n.__base.val;
        n.fx = n.fy = n.fz = undefined;
        continue;
      }
      active = true;
      n.color = mixHex(BIRTH_COLOR, n.__base.color, 1 - heat);
      n.val = n.__base.val * popScale(heat);
      // Hold newborns above the cluster with d3 fixed pins (no fighting
      // the sim), release into a free drop once cooling.
      if (heat > 0.60) {
        const s = spawnOf(id);
        n.fx = s.x;
        n.fy = s.y;
        n.fz = s.z;
      } else {
        n.fx = n.fy = n.fz = undefined;
      }
    }
    // Living organic 3D spatial drift across settled nodes so the graph breathes, moves and floats
    if (!reducedMotion.current && c.nodes.length > 0) {
      const tSec = t * 0.001;
      for (let i = 0; i < c.nodes.length; i++) {
        const n = c.nodes[i];
        if (bornAt.current.has(n.id) || n.id.startsWith("dead:")) continue;
        if (n.__hx === undefined && n.x !== undefined) {
          n.__hx = n.x;
          n.__hy = n.y;
          n.__hz = n.z;
        }
        if (n.__hx !== undefined && n.fx === undefined) {
          // Subtle floating 3D spatial drift: distinct phase per node so they gently float like celestial bodies
          const phase = i * 1.618;
          const driftX = Math.sin(tSec * 0.7 + phase) * 2.8;
          const driftY = Math.cos(tSec * 0.6 + phase * 1.3) * 3.2;
          const driftZ = Math.sin(tSec * 0.8 + phase * 0.7) * 2.4;
          n.x = (n.__hx as number) + driftX;
          n.y = (n.__hy as number) + driftY;
          n.z = (n.__hz as number) + driftZ;

          // Directly synchronize Three.js WebGL mesh position so the 3D sphere moves in real-time
          const threeObj = (n as unknown as { __threeObj?: { position?: { x: number; y: number; z: number } } }).__threeObj;
          if (threeObj?.position) {
            threeObj.position.x = n.x;
            threeObj.position.y = n.y;
            threeObj.position.z = n.z;
          }
        }
      }

      // Synchronize connecting link lines in WebGL so they follow floating nodes
      for (let i = 0; i < c.links.length; i++) {
        const l = c.links[i];
        const start = l.source as unknown as GraphNode;
        const end = l.target as unknown as GraphNode;
        if (!start || !end || typeof start.x !== "number" || typeof end.x !== "number") continue;
        const lineObj = (l as unknown as { __lineObj?: { children?: Array<{ geometry?: { getAttribute?: (name: string) => { array?: Float32Array; needsUpdate?: boolean } } }>; geometry?: { getAttribute?: (name: string) => { array?: Float32Array; needsUpdate?: boolean } } } }).__lineObj;
        if (lineObj) {
          const targetObj = (lineObj.children && lineObj.children.length > 0) ? lineObj.children[0] : lineObj;
          const geom = targetObj?.geometry;
          if (geom?.getAttribute) {
            const posAttr = geom.getAttribute("position");
            if (posAttr?.array && posAttr.array.length >= 6) {
              posAttr.array[0] = start.x;
              posAttr.array[1] = typeof start.y === "number" ? start.y : 0;
              posAttr.array[2] = typeof start.z === "number" ? start.z : 0;
              posAttr.array[3] = end.x;
              posAttr.array[4] = typeof end.y === "number" ? end.y : 0;
              posAttr.array[5] = typeof end.z === "number" ? end.z : 0;
              posAttr.needsUpdate = true;
            }
          }
        }
      }
    }
    for (const l of c.links) {
      const heat = Math.max(
        heatAt(bornAt.current.get(endId(l.source as string | GraphNode)), t, FRESH_MS),
        heatAt(bornAt.current.get(endId(l.target as string | GraphNode)), t, FRESH_MS)
      );
      const glow = heat > 0 ? linkGlowColor(heat) : l.__base;
      if (l.color !== glow) l.color = glow;
    }
    let expiredGhost = false;
    for (const [id, d] of deadAt.current) {
      const p = 1 - (t - d.t) / DIE_MS;
      if (p <= 0) {
        deadAt.current.delete(id);
        c.byId.delete(`dead:${id}`);
        expiredGhost = true;
        continue;
      }
      active = true;
      const gh = c.byId.get(`dead:${id}`);
      if (gh) gh.val = Math.max(0.15, d.val * p);
    }
    if (expiredGhost) setStruct((n) => n + 1); // rebuild minus ghosts
    try {
      if (active) fgRef.current?.refresh?.();
      // Tick OrbitControls auto-rotation if present
      const controls = (fgRef.current as unknown as { controls?: () => { update?: () => void; autoRotate?: boolean; autoRotateSpeed?: number } })?.controls?.();
      if (controls) {
        if (!controls.autoRotate) {
          controls.autoRotate = true;
          controls.autoRotateSpeed = 0.45;
        }
        controls.update?.();
      }
    } catch {
      /* headless test stub */
    }
    if (!reducedMotion.current) {
      loopRef.current = requestAnimationFrame(frame);
    } else if (active) {
      loopRef.current = requestAnimationFrame(frame);
    }
  }, []);

  const kickLoop = useCallback(() => {
    if (loopRef.current !== 0) return;
    loopRef.current = requestAnimationFrame(frame);
  }, [frame]);

  // Adopt the queue head: stamp its birth clock, rebuild to include it
  // (pre-pinned at the sky dock), and let the loop play its drop-in.
  const popOne = useCallback(() => {
    const id = pendingRef.current.shift();
    if (id === undefined) {
      if (popTimer.current) {
        clearInterval(popTimer.current);
        popTimer.current = null;
      }
      return;
    }
    bornAt.current.set(id, Date.now());
    setStruct((n) => n + 1);
    kickLoop();
  }, [kickLoop]);

  useEffect(
    () => () => {
      cancelAnimationFrame(loopRef.current);
      if (popTimer.current) clearInterval(popTimer.current);
    },
    []
  );

  // Stamp births at commit time (≈ first paint — the loop paints heat on
  // its first frame, so event-to-paint lag can't eat the animation).
  useEffect(() => {
    if (!data) return;
    const t = Date.now();
    const live = new Set(data.nodes.map((n) => n.id));
    // An empty refetch against a populated pool is a backend blip, not a
    // massacre: keep the pool (the rebuild does the same) and don't wipe
    // seenIds, or the recovery refetch would flash the whole brain.
    if (live.size === 0 && seenIds.current.size > 0) return;
    // Prune the dead so the maps never grow past the graph.
    for (const id of [...bornAt.current.keys()]) {
      if (!live.has(id)) bornAt.current.delete(id);
    }
    // Queued ids that died before popping never appear: drop them silently.
    if (pendingRef.current.length > 0) {
      pendingRef.current = pendingRef.current.filter((id) => live.has(id));
      if (pendingRef.current.length === 0 && popTimer.current) {
        clearInterval(popTimer.current);
        popTimer.current = null;
      }
    }
    if (!painted.current) {
      // First paint is not a birth: adopt silently, no flashes.
      painted.current = true;
      seenIds.current = live;
      onReadyRef.current?.();
      if (!reducedMotion.current) kickLoop();
      return;
    }
    const fresh = data.nodes.filter((n) => !seenIds.current.has(n.id));
    seenIds.current = live;
    if (fresh.length === 0) {
      // Deaths alone still animate — but a pure no-op refetch must not
      // even schedule a frame, or "zero digest" is a lie.
      for (const d of deadAt.current.values()) {
        if (t - d.t < DIE_MS) {
          kickLoop();
          break;
        }
      }
      return;
    }
    const stamped = fresh.map((n) => n.id);
    burstIds.current = stamped;
    setBurst({ ids: stamped, at: t });
    if (reducedMotion.current) {
      for (const id of stamped) bornAt.current.set(id, t);
      kickLoop(); // no-op under reduced motion: births render settled
      return;
    }
    // Sequential adoption: the headliner pops now, the rest one per beat.
    pendingRef.current.push(...stamped);
    popOne();
    if (!popTimer.current && pendingRef.current.length > 0) {
      popTimer.current = setInterval(popOne, birthGapMs);
    }
    kickLoop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

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
    burstIds.current = [];
    pendingRef.current = [];
    if (popTimer.current) {
      clearInterval(popTimer.current);
      popTimer.current = null;
    }
    painted.current = false;
    framed.current = false;
    cancelAnimationFrame(loopRef.current);
    loopRef.current = 0;
    cache.current = emptyCache();
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
      const pn = cache.current.byId.get(id);
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

  // Stable callback identity: a fresh closure per render would re-trigger
  // the lib's object digest on every React commit (no reheat, but churn).
  const onPath = useCallback(
    (l: GraphLink): number =>
      pathSet.current.size > 0 &&
      pathSet.current.has(endId(l.source)) &&
      pathSet.current.has(endId(l.target))
        ? 3
        : 0,
    []
  );

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
  const pathKey = path.join("\0");

  // Reconcile the fetch payload into the pooled graph. Survivors keep
  // their object identity (sim coords, velocity, pins untouched); only
  // true membership changes mint a new wrapper — and only a new wrapper
  // makes the lib pause + reheat. A refetch with identical rows is free.
  const rebuildCache = (vis: Set<string> | null) => {
    const cc = cache.current;
    // Empty blip guard (mirrors the stamp effect): keep the pool.
    if (data.nodes.length === 0 && cc.byId.size > 0) {
      cc.data = data;
      return;
    }
    const onPathSet = pathSet.current;
    const live = new Set(data.nodes.map((n) => n.id));
    if (!reducedMotion.current) {
      const unpopped = new Set(pendingRef.current);
      for (const [id, pn] of cc.byId) {
        if (id.startsWith("dead:") || live.has(id) || deadAt.current.has(id)) continue;
        if (unpopped.has(id)) continue; // never appeared: no death scene
        deadAt.current.set(id, {
          t: Date.now(),
          x: pn.x ?? 0,
          y: pn.y ?? 0,
          z: pn.z ?? 0,
          val: pn.val ?? 2,
        });
      }
    }
    const byId = new Map<string, FGNode>();
    for (const n of data.nodes) {
      const base = baseDisplay(n, onPathSet.has(n.id));
      const prev = cc.byId.get(n.id);
      if (prev) {
        prev.label = n.label;
        prev.tier = n.tier;
        prev.tags = n.tags;
        prev.salience = n.salience;
        prev.quarantined = n.quarantined;
        prev.ranked_out = n.ranked_out;
        const baseChanged =
          prev.__base.color !== base.color || prev.__base.val !== base.val;
        prev.__base = base;
        // A burning node belongs to the loop; otherwise settle + repaint.
        if (!bornAt.current.has(n.id) && baseChanged) {
          prev.color = base.color;
          prev.val = base.val;
          kickLoop();
        }
        byId.set(n.id, prev);
      } else {
        const obj: FGNode = {
          ...n, color: base.color, val: base.val, __base: base,
        };
        if (painted.current) {
          // True birth (never first paint): seed + pin at the sky dock
          // BEFORE the sim's first tick. Otherwise d3 plants the newborn
          // at the spiral center and the alpha=1 reheat kicks the brain.
          const s = spawnOf(n.id);
          obj.x = obj.fx = s.x;
          obj.y = obj.fy = s.y;
          obj.z = obj.fz = s.z;
        }
        byId.set(n.id, obj);
      }
    }
    const nodes: FGNode[] = [];
    const queued = new Set(pendingRef.current);
    for (const n of data.nodes) {
      if (vis && !vis.has(n.id)) continue;
      if (queued.has(n.id)) continue; // unpopped: appears on its own beat
      nodes.push(byId.get(n.id)!);
    }
    for (const [id, d] of deadAt.current) {
      if (Date.now() - d.t >= DIE_MS) {
        deadAt.current.delete(id);
        continue;
      }
      const gid = `dead:${id}`;
      let gh = cc.byId.get(gid);
      if (!gh) {
        gh = {
          id: gid, label: "", tier: "", tags: [], salience: 0,
          quarantined: false, color: "#d9534f", val: d.val,
          x: d.x, y: d.y, z: d.z, fx: d.x, fy: d.y, fz: d.z,
          __base: { color: "#d9534f", val: d.val },
        };
      }
      byId.set(gid, gh);
      nodes.push(gh);
    }
    const links: FGLink[] = [];
    const linkByKey = new Map<string, FGLink>();
    const seenK = new Set<string>();
    for (const l of data.links) {
      if (vis && !(vis.has(l.source) && vis.has(l.target))) continue;
      if (queued.has(l.source) || queued.has(l.target)) continue;
      const k = `${l.source}>${l.target}:${l.relation}`;
      if (seenK.has(k)) continue;
      seenK.add(k);
      const base = linkBaseColor(
        l.relation, onPathSet.has(l.source) && onPathSet.has(l.target));
      const prev = cc.linkByKey.get(k);
      if (prev) {
        if (prev.__base !== base) {
          prev.__base = base;
          prev.color = base;
          kickLoop();
        }
        prev.reason = l.reason ?? l.relation;
        links.push(prev);
      } else {
        links.push({ ...l, color: base, __base: base });
      }
      linkByKey.set(k, links[links.length - 1]);
    }
    const sameNodes =
      nodes.length === cc.nodes.length && nodes.every((n, i) => n === cc.nodes[i]);
    const sameLinks =
      links.length === cc.links.length && links.every((l, i) => l === cc.links[i]);
    cc.data = data;
    cc.area = area;
    cc.pathKey = pathKey;
    cc.struct = struct;
    cc.byId = byId;
    cc.linkByKey = linkByKey;
    if (sameNodes && sameLinks) return; // zero digest, zero reheat
    cc.nodes = nodes;
    cc.links = links;
    cc.graphData = { nodes, links };
  };
  const cc = cache.current;
  if (cc.data !== data || cc.area !== area || cc.pathKey !== pathKey || cc.struct !== struct) {
    rebuildCache(visibleIds);
  }

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
          className="absolute top-2 left-1/2 -translate-x-1/2 z-10 card px-3 py-1.5 text-xs mono border border-cyan-500/50 shadow-[0_0_15px_rgba(6,182,212,0.4)] animate-pulse"
        >
          <span className="livedot live mr-1" /> {burst.ids.length} new — show me
        </button>
      )}
      <Suspense fallback={<p className="dim text-sm">growing the brain…</p>}>
      <ForceGraph3D
        ref={fgRef}
        graphData={cc.graphData}
        nodeLabel="label"
        nodeColor="color"
        nodeVal="val"
        linkColor="color"
        linkLabel="reason"
        linkWidth={1.3}
        linkDirectionalParticles={(l) => {
          const src = endId(l.source as string | GraphNode);
          const tgt = endId(l.target as string | GraphNode);
          const isFresh = bornAt.current.has(src) || bornAt.current.has(tgt);
          return isFresh ? 4 : onPath(l);
        }}
        linkDirectionalParticleSpeed={0.008}
        linkDirectionalParticleColor={(l) => {
          const src = endId(l.source as string | GraphNode);
          const tgt = endId(l.target as string | GraphNode);
          return bornAt.current.has(src) || bornAt.current.has(tgt)
            ? BIRTH_COLOR
            : "#ffffff";
        }}
        backgroundColor="#101014"
        showNavInfo={false}
        enableNodeDrag={true}
        onNodeClick={onNodeClick}
        cooldownTime={12000}
        d3VelocityDecay={0.6}
        d3AlphaDecay={0.035}
        onEngineStop={() => {
          if (framed.current || cache.current.nodes.length === 0) return;
          framed.current = true;
          try {
            fgRef.current?.zoomToFit?.(
              reducedMotion.current ? 0 : 800, 70
            );
            const controls = (fgRef.current as unknown as { controls?: () => { autoRotate?: boolean; autoRotateSpeed?: number } })?.controls?.();
            if (controls) {
              controls.autoRotate = true;
              controls.autoRotateSpeed = 0.45;
            }
          } catch {
            /* graph not ready */
          }
        }}
      />
      </Suspense>
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

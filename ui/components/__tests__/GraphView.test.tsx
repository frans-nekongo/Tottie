import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import GraphView from "../GraphView";
import { spawnOf } from "../graphMath";

// The GL renderer is third-party: stub it, capture exactly what Tottie
// feeds it, and expose the camera API as spies. Everything else is real.
vi.mock("react-force-graph-3d", () => ({
  default: (props: Record<string, unknown>) => {
    const g = globalThis as Record<string, unknown>;
    g.__fgProps = props;
    const ref = props.ref as { current: unknown } | undefined;
    if (ref && typeof ref === "object") ref.current = g.__fgInstance;
    return null;
  },
}));

interface FGNode {
  id: string;
  color: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [k: string]: any;
}

const g = () => globalThis as unknown as Record<string, unknown>;
const fgGraphData = () =>
  (g().__fgProps as { graphData: { nodes: FGNode[] } }).graphData;
const fgNodes = () => fgGraphData().nodes;
const fgSpy = () =>
  g().__fgInstance as { cameraPosition: ReturnType<typeof vi.fn> };
const refreshSpy = () =>
  g().__fgInstance as { refresh: ReturnType<typeof vi.fn> };

type G = { nodes: Record<string, unknown>[]; links: Record<string, unknown>[] };
const node = (id: string, tier = "knowledge", salience = 0.5, tags: string[] = []) => ({
  id,
  label: `label ${id}`,
  tier,
  tags,
  salience,
  quarantined: false,
});

let graphResponses: G[];
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  graphResponses = [];
  g().__fgProps = undefined;
  g().__fgInstance = { cameraPosition: vi.fn(), zoomToFit: vi.fn(), refresh: vi.fn() };
  fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const calls = fetchMock.mock.calls.filter(([u]) =>
      String(u).startsWith("/api/graph")
    ).length;
    const body = graphResponses[Math.min(calls - 1, graphResponses.length - 1)];
    return { ok: true, json: async () => body };
  });
  vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);
});

afterEach(() => {
  window.matchMedia = g().__defaultMatchMedia as typeof window.matchMedia;
});

const graphCalls = () =>
  fetchMock.mock.calls.filter(([u]) => String(u).startsWith("/api/graph")).length;

const renderGraph = (fresh = 0, onSync = vi.fn()) =>
  render(<GraphView path={[]} fresh={fresh} owner="o" onSync={onSync} />);

describe("GraphView", () => {
  it("maps fetched nodes to tier colors and reports sync ms", async () => {
    graphResponses = [
      { nodes: [node("a"), node("b", "episodic")], links: [] },
    ];
    const onSync = vi.fn();
    renderGraph(0, onSync);
    await waitFor(() => expect(graphCalls()).toBe(1));
    await waitFor(() => expect(onSync).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(g().__fgProps).toBeDefined());
    expect(onSync.mock.calls[0][0]).toEqual(expect.any(Number));
    expect(onSync.mock.calls[0][0]).toBeGreaterThanOrEqual(0);
    const byId = Object.fromEntries(fgNodes().map((n) => [n.id, n]));
    expect(byId.a.color).toBe("#9a7bd0"); // knowledge tier, settled
    expect(byId.b.color).toBe("#4cc3d9"); // episodic tier
    expect(byId.a.val).toBe(2.5); // (1 + 0.5*3), no heat on first paint
  });

  it("adopts the first paint silently: no pill, no heat", async () => {
    graphResponses = [{ nodes: [node("a"), node("b")], links: [] }];
    renderGraph();
    await waitFor(() => expect(graphCalls()).toBe(1));
    await waitFor(() =>
      expect(fgNodes().map((n) => n.id).sort()).toEqual(["a", "b"])
    );
    expect(screen.queryByRole("button", { name: /show me/ })).toBeNull();
    for (const n of fgNodes()) expect(n.color).toBe("#9a7bd0");
  });

  it("pops newborns white-hot with a pill on the next refetch", async () => {
    graphResponses = [
      { nodes: [node("a")], links: [] },
      { nodes: [node("a"), node("n")], links: [] },
    ];
    const { rerender } = renderGraph(0);
    await waitFor(() => expect(graphCalls()).toBe(1));
    rerender(<GraphView path={[]} fresh={1} owner="o" />);
    const pill = await screen.findByRole("button", { name: /1 new/ });
    expect(pill).toHaveTextContent("1 new — show me");
    // Heat is painted by the rAF loop, not the commit: wait for it.
    await waitFor(() => {
      const born = fgNodes().find((n) => n.id === "n")!;
      expect(born.color).not.toBe("#9a7bd0"); // white-hot, not tier color
      expect(born.val).toBeGreaterThan(2.5); // size-boosted pop
    });
  });

  it("holds graphData identity while heat animates (no reheat)", async () => {
    graphResponses = [
      { nodes: [node("a")], links: [] },
      { nodes: [node("a"), node("n")], links: [] },
    ];
    const { rerender } = renderGraph(0);
    await waitFor(() => expect(graphCalls()).toBe(1));
    rerender(<GraphView path={[]} fresh={1} owner="o" />);
    await screen.findByRole("button", { name: /1 new/ });
    await waitFor(() => {
      expect(fgNodes().find((n) => n.id === "n")!.color).not.toBe("#9a7bd0");
    });
    const wrapper = fgGraphData();
    const arr = fgNodes();
    const before = arr.find((n) => n.id === "n")!.color;
    await new Promise((r) => setTimeout(r, 400));
    // Same references the lib compares by: zero digest, zero reheat —
    // yet the animation visibly progressed via refresh().
    expect(fgGraphData()).toBe(wrapper);
    expect(fgNodes()).toBe(arr);
    expect(fgNodes().find((n) => n.id === "n")!.color).not.toBe(before);
    expect(refreshSpy().refresh).toHaveBeenCalled();
  });

  it("treats an identical refetch as a no-op (zero digest)", async () => {
    graphResponses = [
      { nodes: [node("a")], links: [] },
      { nodes: [node("a")], links: [] },
    ];
    const { rerender } = renderGraph(0);
    await waitFor(() => expect(graphCalls()).toBe(1));
    await waitFor(() => expect(g().__fgProps).toBeDefined());
    const wrapper = fgGraphData();
    rerender(<GraphView path={[]} fresh={1} owner="o" />);
    await waitFor(() => expect(graphCalls()).toBe(2));
    await new Promise((r) => setTimeout(r, 150));
    expect(fgGraphData()).toBe(wrapper);
    expect(refreshSpy().refresh).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /show me/ })).toBeNull();
  });

  it("shrinks removed ids out red where they fell", async () => {
    graphResponses = [
      { nodes: [node("a"), node("b")], links: [] },
      { nodes: [node("a")], links: [] },
    ];
    const { rerender } = renderGraph(0);
    await waitFor(() => expect(graphCalls()).toBe(1));
    rerender(<GraphView path={[]} fresh={1} owner="o" />);
    await waitFor(() => {
      const ghost = fgNodes().find((n) => n.id === "dead:b");
      expect(ghost).toBeDefined();
      expect(ghost!.color).toBe("#d9534f");
    });
  });

  it("flies the pill click to the newborn centroid", async () => {
    graphResponses = [
      { nodes: [node("a")], links: [] },
      { nodes: [node("a"), node("n")], links: [] },
    ];
    const { rerender } = renderGraph(0);
    await waitFor(() => expect(graphCalls()).toBe(1));
    rerender(<GraphView path={[]} fresh={1} owner="o" />);
    const pill = await screen.findByRole("button", { name: /1 new/ });
    fireEvent.click(pill);
    const c = spawnOf("n"); // no sim in jsdom: spawn coords are exact
    expect(fgSpy().cameraPosition).toHaveBeenCalledTimes(1);
    expect(fgSpy().cameraPosition).toHaveBeenCalledWith(
      { x: c.x, y: c.y + 55, z: c.z + 220 },
      c,
      800
    );
    expect(screen.queryByRole("button", { name: /show me/ })).toBeNull();
  });

  it("filters by area chip and clears the filter on fly-to", async () => {
    graphResponses = [
      { nodes: [node("a", "knowledge", 0.5, ["area:x"]), node("b", "knowledge", 0.5, ["area:y"])], links: [] },
      { nodes: [node("a", "knowledge", 0.5, ["area:x"]), node("b", "knowledge", 0.5, ["area:y"]), node("c", "knowledge", 0.5, ["area:y"])], links: [] },
    ];
    const { rerender } = renderGraph(0);
    const chip = await screen.findByRole("button", { name: /x 1/ });
    fireEvent.click(chip);
    await waitFor(() =>
      expect(fgNodes().map((n) => n.id)).toEqual(["a"])
    );
    rerender(<GraphView path={[]} fresh={1} owner="o" />);
    const pill = await screen.findByRole("button", { name: /1 new/ });
    fireEvent.click(pill);
    await waitFor(() =>
      expect(fgNodes().map((n) => n.id).sort()).toEqual(["a", "b", "c"])
    );
    expect(fgSpy().cameraPosition).toHaveBeenCalledTimes(1);
  });

  it("renders births settled under reduced motion", async () => {
    window.matchMedia = (() => ({ matches: true })) as unknown as typeof window.matchMedia;
    graphResponses = [
      { nodes: [node("a")], links: [] },
      { nodes: [node("a"), node("n")], links: [] },
    ];
    const { rerender } = renderGraph(0);
    await waitFor(() => expect(graphCalls()).toBe(1));
    rerender(<GraphView path={[]} fresh={1} owner="o" />);
    await screen.findByRole("button", { name: /1 new/ });
    const born = fgNodes().find((n) => n.id === "n")!;
    expect(born.color).toBe("#9a7bd0");
    expect(born.val).toBe(2.5);
  });

  it("shows unavailable on fetch failure", async () => {
    fetchMock.mockImplementationOnce(async () => ({ ok: false, status: 500 }));
    graphResponses = [{ nodes: [], links: [] }];
    renderGraph();
    await screen.findByText(/graph unavailable/);
  });

  it("does not refetch when the fresh prop is unchanged", async () => {
    graphResponses = [{ nodes: [node("a")], links: [] }];
    const onSync = vi.fn();
    const { rerender } = renderGraph(0, onSync);
    await waitFor(() => expect(graphCalls()).toBe(1));
    rerender(<GraphView path={[]} fresh={0} owner="o" onSync={onSync} />);
    await new Promise((r) => setTimeout(r, 100));
    expect(graphCalls()).toBe(1);
  });

  it("seeds and pins newborns at the sky dock before the first frame", async () => {
    graphResponses = [
      { nodes: [node("a")], links: [] },
      { nodes: [node("a"), node("n")], links: [] },
    ];
    const { rerender } = renderGraph(0);
    await waitFor(() => expect(graphCalls()).toBe(1));
    const settled = fgNodes().find((n) => n.id === "a")!;
    expect(settled.fx).toBeUndefined(); // first paint: free, never pinned
    rerender(<GraphView path={[]} fresh={1} owner="o" />);
    await screen.findByRole("button", { name: /1 new/ });
    const s = spawnOf("n");
    const born = fgNodes().find((n) => n.id === "n")!;
    // Born pinned at the dock: the sim never sees the spiral center.
    expect({ x: born.x, y: born.y, z: born.z }).toEqual(s);
    expect({ x: born.fx, y: born.fy, z: born.fz }).toEqual(s);
    const props = g().__fgProps as Record<string, unknown>;
    expect(props.d3VelocityDecay).toBe(0.6);
    expect(props.d3AlphaDecay).toBe(0.035);
  });

  it("adopts burst newborns one per beat, headliner first", async () => {
    graphResponses = [
      { nodes: [node("a")], links: [] },
      { nodes: [node("a"), node("n1"), node("n2"), node("n3")], links: [] },
    ];
    const { rerender } = render(
      <GraphView path={[]} fresh={0} owner="o" birthGapMs={60} />
    );
    await waitFor(() => expect(graphCalls()).toBe(1));
    rerender(<GraphView path={[]} fresh={1} owner="o" birthGapMs={60} />);
    await screen.findByRole("button", { name: /3 new/ });
    // Headliner pops sync; the tail is still queued, not shown.
    expect(fgNodes().map((n) => n.id)).toContain("n1");
    expect(fgNodes().map((n) => n.id)).not.toContain("n3");
    await waitFor(() =>
      expect(fgNodes().map((n) => n.id).sort()).toEqual(["a", "n1", "n2", "n3"])
    );
  });

  it("drops queued ids that die before popping", async () => {
    graphResponses = [
      { nodes: [node("a")], links: [] },
      { nodes: [node("a"), node("n1"), node("n2")], links: [] },
      { nodes: [node("a"), node("n1")], links: [] },
    ];
    const { rerender, unmount } = render(
      <GraphView path={[]} fresh={0} owner="o" birthGapMs={5000} />
    );
    await waitFor(() => expect(graphCalls()).toBe(1));
    rerender(<GraphView path={[]} fresh={1} owner="o" birthGapMs={5000} />);
    await screen.findByRole("button", { name: /2 new/ });
    expect(fgNodes().map((n) => n.id).sort()).toEqual(["a", "n1"]);
    // n2 vanishes upstream before its beat: pruned, never shown, no ghost.
    rerender(<GraphView path={[]} fresh={2} owner="o" birthGapMs={5000} />);
    await waitFor(() => expect(graphCalls()).toBe(3));
    await new Promise((r) => setTimeout(r, 150));
    expect(fgNodes().map((n) => n.id).sort()).toEqual(["a", "n1"]);
    expect(fgNodes().find((n) => n.id === "dead:n2")).toBeUndefined();
    unmount();
  });

  it("drops a stale fetch that lands after a newer refetch", async () => {
    let release!: (v: unknown) => void;
    const gate = new Promise((r) => (release = r));
    fetchMock.mockImplementation(async () => {
      const n = fetchMock.mock.calls.filter(([u]) =>
        String(u).startsWith("/api/graph")
      ).length;
      if (n === 1) {
        return {
          ok: true,
          json: async () => {
            await gate; // stale by design: resolves last
            return { nodes: [node("a"), node("stale")], links: [] };
          },
        };
      }
      return {
        ok: true,
        json: async () => ({ nodes: [node("a")], links: [] }),
      };
    });
    const onSync = vi.fn();
    const { rerender } = renderGraph(0, onSync);
    await waitFor(() => expect(graphCalls()).toBe(1));
    rerender(<GraphView path={[]} fresh={1} owner="o" onSync={onSync} />);
    await waitFor(() => expect(graphCalls()).toBe(2));
    await waitFor(() => expect(onSync).toHaveBeenCalledTimes(1));
    release(null); // the stale first response lands now — and dies
    await new Promise((r) => setTimeout(r, 150));
    expect(fgNodes().map((n) => n.id).sort()).toEqual(["a"]);
    expect(onSync).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /show me/ })).toBeNull();
  });

  it("frames the whole graph once when the engine settles", async () => {
    graphResponses = [
      { nodes: [], links: [] },
      { nodes: [node("a"), node("b")], links: [] },
    ];
    const { rerender } = renderGraph(0);
    await waitFor(() => expect(graphCalls()).toBe(1));
    await waitFor(() => expect(g().__fgProps).toBeDefined());
    const ztf = () =>
      (g().__fgInstance as { zoomToFit: ReturnType<typeof vi.fn> }).zoomToFit;
    const stop = () =>
      (g().__fgProps as { onEngineStop: () => void }).onEngineStop;
    // Empty pool: skip, a later stop retries.
    stop()();
    expect(ztf()).not.toHaveBeenCalled();
    rerender(<GraphView path={[]} fresh={1} owner="o" />);
    await waitFor(() => expect(fgNodes().length).toBe(2));
    stop()();
    expect(ztf()).toHaveBeenCalledTimes(1);
    // Later stops must not yank the camera again.
    stop()();
    expect(ztf()).toHaveBeenCalledTimes(1);
  });
});

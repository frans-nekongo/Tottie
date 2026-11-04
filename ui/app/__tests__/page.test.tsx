import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Home from "../page";

// Renderer stub (same contract as the GraphView suite): capture props,
// expose the camera API. The stream, the refetch, the feed are all real.
vi.mock("react-force-graph-3d", () => ({
  default: (props: Record<string, unknown>) => {
    const g = globalThis as Record<string, unknown>;
    g.__fgProps = props;
    const ref = props.ref as { current: unknown } | undefined;
    if (ref && typeof ref === "object") ref.current = g.__fgInstance;
    return null;
  },
}));

type Frame = { data: string };
class MockES {
  static instances: MockES[] = [];
  url: string;
  listeners: Record<string, Array<(m: Frame) => void>> = {};
  onmessage: ((m: Frame) => void) | null = null;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(url: string) {
    this.url = url;
    MockES.instances.push(this);
  }
  addEventListener(t: string, f: (m: Frame) => void) {
    (this.listeners[t] ??= []).push(f);
  }
  removeEventListener() {}
  emit(t: string, data: unknown) {
    const body = typeof data === "string" ? data : JSON.stringify(data);
    for (const f of this.listeners[t] ?? []) f({ data: body });
  }
  sendUnnamed(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
  close() {}
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let fetchMock: ReturnType<typeof vi.fn>;
let graphBody = { nodes: [], links: [] };

beforeEach(() => {
  MockES.instances = [];
  graphBody = { nodes: [], links: [] };
  fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const u = String(input);
    if (u.startsWith("/api/graph"))
      return { ok: true, json: async () => graphBody };
    if (u.startsWith("/api/agents"))
      return { ok: true, json: async () => ({ agents: [] }) };
    if (u.startsWith("/api/memories"))
      return { ok: true, json: async () => ({ memories: [] }) };
    return { ok: true, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);
  vi.stubGlobal("EventSource", MockES as unknown as typeof EventSource);
});

const graphCalls = () =>
  fetchMock.mock.calls.filter(([u]) => String(u).startsWith("/api/graph")).length;
const es = () => MockES.instances[MockES.instances.length - 1];
const tick = (ms = 100) => new Promise((r) => setTimeout(r, ms));

const memEvent = (op: string, utterance: string | null) => ({
  id: "uuid-1",
  ts: "2026-11-03",
  turn: 0,
  utterance,
  verdict: null,
  action: { op, memory_ids: ["uuid-1"] },
  cue: null,
  latency_ms: 5,
  tokens: 3,
});

async function openBrain() {
  render(<Home />);
  await waitFor(() => expect(MockES.instances.length).toBe(1));
  fireEvent.click(screen.getByRole("button", { name: "3D brain" }));
  await waitFor(() => expect(graphCalls()).toBe(1));
  // The gate opens on adoption, not on fetch: wait for first data.
  await waitFor(() =>
    expect(screen.queryByText(/growing the brain/)).toBeNull()
  );
}

describe("Home stream wiring", () => {
  it("refetches the brain and shows the memory on a named NEW event", async () => {
    await openBrain();
    act(() => {
      es().emit("memory", memEvent("NEW", "The vault code is AR-4401."));
    });
    await screen.findByText("The vault code is AR-4401.");
    await waitFor(() => expect(graphCalls()).toBe(2));
    expect(screen.getByLabelText("Tottie remembering")).toBeInTheDocument();
  });

  it("shows SUPERSEDE kills with the red chip", async () => {
    await openBrain();
    act(() => {
      es().emit("memory", memEvent("SUPERSEDE", "Correction: the code is AR-4402."));
    });
    await screen.findByText("Correction: the code is AR-4402.");
    expect(document.querySelector(".op-SUPERSEDE")).not.toBeNull();
    await waitFor(() => expect(graphCalls()).toBe(2));
  });

  it("refetches on other ops without feed or flash", async () => {
    await openBrain();
    act(() => {
      es().emit("memory", memEvent("RECALL", "something recalled"));
    });
    await waitFor(() => expect(graphCalls()).toBe(2));
    expect(screen.queryByText("something recalled")).toBeNull();
    expect(screen.getByLabelText("Tottie idle")).toBeInTheDocument();
  });

  it("survives malformed frames and keeps the stream alive", async () => {
    await openBrain();
    act(() => {
      es().emit("memory", "{oops");
    });
    await tick();
    expect(graphCalls()).toBe(1);
    act(() => {
      es().emit("memory", memEvent("NEW", "still alive"));
    });
    await screen.findByText("still alive");
  });

  it("ignores event names nobody listens for", async () => {
    await openBrain();
    act(() => {
      es().emit("ping", memEvent("NEW", "no listener for this"));
    });
    await tick();
    expect(graphCalls()).toBe(1);
    expect(screen.queryByText("no listener for this")).toBeNull();
  });

  it("honors the defensive unnamed-message path", async () => {
    await openBrain();
    act(() => {
      es().sendUnnamed(memEvent("NEW", "via onmessage"));
    });
    await screen.findByText("via onmessage");
    await waitFor(() => expect(graphCalls()).toBe(2));
  });

  it("opens no stream when ?stream=off", async () => {
    window.history.replaceState(null, "", "/?stream=off");
    try {
      render(<Home />);
      await tick(150);
      expect(MockES.instances.length).toBe(0);
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });

  it("tracks connection state on the live dot", async () => {
    await openBrain();
    act(() => {
      es().onopen?.();
    });
    expect(screen.getByTitle("stream live")).toBeInTheDocument();
    act(() => {
      es().onerror?.();
    });
    expect(screen.getByTitle("stream reconnecting")).toBeInTheDocument();
  });

  it("shows the last sync round-trip in the subtitle", async () => {
    await openBrain();
    expect(await screen.findByText(/sync \d+ms/)).toBeInTheDocument();
  });

  it("holds feed and flash until the graph adopts first data", async () => {
    // Hold the first graph fetch pending: the brain is still "growing".
    let release!: (v: unknown) => void;
    const gate = new Promise((r) => (release = r));
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const u = String(input);
      if (u.startsWith("/api/graph")) {
        return { ok: true, json: async () => (await gate, graphBody) };
      }
      if (u.startsWith("/api/agents"))
        return { ok: true, json: async () => ({ agents: [] }) };
      if (u.startsWith("/api/memories"))
        return { ok: true, json: async () => ({ memories: [] }) };
      return { ok: true, json: async () => ({}) };
    });
    render(<Home />);
    await waitFor(() => expect(MockES.instances.length).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: "3D brain" }));
    await screen.findByText(/growing the brain/);
    act(() => {
      es().emit("memory", memEvent("NEW", "early bird"));
    });
    await tick(150);
    // Pre-ready: no notification, no flash — but the tick still fired,
    // so the graph catches up the moment data lands.
    expect(screen.queryByText("early bird")).toBeNull();
    expect(screen.getByLabelText("Tottie idle")).toBeInTheDocument();
    expect(graphCalls()).toBe(2);
    release(null);
    await waitFor(() =>
      expect(screen.queryByText(/growing the brain/)).toBeNull()
    );
    act(() => {
      es().emit("memory", memEvent("NEW", "after ready"));
    });
    await screen.findByText("after ready");
    expect(screen.getByLabelText("Tottie remembering")).toBeInTheDocument();
  });
});

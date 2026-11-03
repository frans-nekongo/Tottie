import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// Deterministic frame clock: jsdom has no display, so births stamp on a
// 16ms timer instead of a real vsync signal. Direct assignment (not
// stubGlobal) so per-test unstubAllGlobals doesn't remove it.
globalThis.requestAnimationFrame = ((cb: FrameRequestCallback) =>
  setTimeout(() => cb(Date.now()), 16) as unknown as number);
globalThis.cancelAnimationFrame = ((id: number) => clearTimeout(id));

const matchMediaImpl = (matches: boolean) => () => ({
  matches,
  media: "",
  onchange: null,
  addListener: vi.fn(),
  removeListener: vi.fn(),
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  dispatchEvent: vi.fn(),
});

// Default: motion allowed. Tests that need reduced motion override
// window.matchMedia before render and restore it after.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: matchMediaImpl(false),
});
(globalThis as Record<string, unknown>).__defaultMatchMedia =
  window.matchMedia;

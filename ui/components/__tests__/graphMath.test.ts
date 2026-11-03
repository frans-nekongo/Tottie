import { describe, expect, it } from "vitest";
import { hashStr, heatAt, mixHex, popScale, spawnOf } from "../graphMath";

describe("mixHex", () => {
  it("returns the endpoints at t=0 and t=1", () => {
    expect(mixHex("#ffffff", "#9a7bd0", 0)).toBe("#ffffff");
    expect(mixHex("#ffffff", "#9a7bd0", 1)).toBe("#9a7bd0");
  });

  it("midpoints white and black to gray", () => {
    expect(mixHex("#ffffff", "#000000", 0.5)).toBe("#808080");
  });
});

describe("hashStr", () => {
  it("is deterministic in [0, 1) and differs across inputs", () => {
    expect(hashStr("abc")).toBe(hashStr("abc"));
    const h = hashStr("abc");
    expect(h).toBeGreaterThanOrEqual(0);
    expect(h).toBeLessThan(1);
    expect(hashStr("abc")).not.toBe(hashStr("abd"));
  });
});

describe("spawnOf", () => {
  it("scatters deterministically above the cluster", () => {
    const a = spawnOf("id-1");
    expect(a).toEqual(spawnOf("id-1"));
    expect(a.y).toBeGreaterThanOrEqual(130);
    expect(a.y).toBeLessThanOrEqual(180);
    expect(Math.abs(a.x)).toBeLessThanOrEqual(35);
    expect(Math.abs(a.z)).toBeLessThanOrEqual(35);
    expect(spawnOf("id-2")).not.toEqual(a);
  });
});

describe("heatAt", () => {
  it("cools linearly from 1 to 0 across the window", () => {
    expect(heatAt(1000, 1000, 2600)).toBe(1);
    expect(heatAt(0, 1300, 2600)).toBeCloseTo(0.5, 9);
    expect(heatAt(0, 2599, 2600)).toBeGreaterThan(0);
  });

  it("is zero for unknown, future, and expired births", () => {
    expect(heatAt(undefined, 1000)).toBe(0);
    expect(heatAt(2000, 1000)).toBe(0);
    expect(heatAt(0, 2600, 2600)).toBe(0);
    expect(heatAt(0, 99999, 2600)).toBe(0);
  });

  it("honors a custom window", () => {
    expect(heatAt(0, 500, 1000)).toBeCloseTo(0.5, 9);
  });
});

describe("popScale", () => {
  it("is 1 settled and 2.2 at full heat", () => {
    expect(popScale(0)).toBe(1);
    expect(popScale(1)).toBeCloseTo(2.2, 9);
  });

  it("shrinks monotonically and clamps negative heat", () => {
    expect(popScale(0.5)).toBeGreaterThan(popScale(0.25));
    expect(popScale(0.25)).toBeGreaterThan(1);
    expect(popScale(-3)).toBe(1);
  });
});

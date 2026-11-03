// Pure animation math for the 3D brain: heat decay, pop easing, spawn
// layout, color mixing. No React, no three.js — unit-tested directly.

export function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

export function mixHex(a: string, b: string, t: number): string {
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

export function spawnOf(id: string): { x: number; y: number; z: number } {
  // Newborns spawn high above the cluster; the force layout pulls them
  // down into place — a literal drop-in. Deterministic scatter per id
  // so siblings don't stack.
  const h1 = hashStr(id);
  const h2 = hashStr(id + ":z");
  return { x: (h1 - 0.5) * 70, y: 130 + h1 * 50, z: (h2 - 0.5) * 70 };
}

export function heatAt(
  birth: number | undefined,
  clock: number,
  windowMs = 2600
): number {
  // 1 = just born, 0 = cooled. Absent birth = long settled.
  if (birth === undefined) return 0;
  const age = clock - birth;
  if (age < 0 || age >= windowMs) return 0;
  return 1 - age / windowMs;
}

export function popScale(heat: number): number {
  // Ease-out pop: violent shrink at first, gentle settle at the end.
  return 1 + 1.2 * Math.pow(Math.max(0, heat), 1.5);
}

"use client";

import { useEffect, useState } from "react";

export type FaceState = "idle" | "listening" | "thinking" | "remembering" | "speaking";

// Placeholder contract: drop frame-*.png sets into public/tottie/<state>/ and
// they render with zero code change; until then the SVG faces below ship.
const PNG = (state: string) => `/tottie/${state}/frame-0.png`;

const HUES: Record<FaceState, string> = {
  idle: "#a3a099",
  listening: "#4cc3d9",
  thinking: "#d9a441",
  remembering: "#9a7bd0",
  speaking: "#6fbf73",
};

function SvgFace({ state }: { state: FaceState }) {
  const c = HUES[state];
  const mouth =
    state === "speaking" ? (
      <ellipse cx="50" cy="66" rx="9" ry="6" fill={c} />
    ) : state === "thinking" ? (
      <line x1="40" y1="67" x2="60" y2="63" stroke={c} strokeWidth="3" strokeLinecap="round" />
    ) : (
      <line x1="40" y1="65" x2="60" y2="65" stroke={c} strokeWidth="3" strokeLinecap="round" />
    );
  const eyes =
    state === "remembering" ? (
      <>
        <circle cx="38" cy="42" r="6" fill="none" stroke={c} strokeWidth="3" />
        <circle cx="62" cy="42" r="6" fill="none" stroke={c} strokeWidth="3" />
        <circle cx="38" cy="42" r="2" fill={c} />
        <circle cx="62" cy="42" r="2" fill={c} />
      </>
    ) : (
      <>
        <circle cx="38" cy="42" r="4.5" fill={c} />
        <circle cx="62" cy="42" r="4.5" fill={c} />
      </>
    );
  return (
    <svg viewBox="0 0 100 100" width="72" height="72" role="img" aria-label={`Tottie ${state}`}>
      <circle cx="50" cy="50" r="44" fill="none" stroke={c} strokeWidth="3" opacity="0.7" />
      {eyes}
      {mouth}
    </svg>
  );
}

export default function TottieFace({ state }: { state: FaceState }) {
  // SVG first: an SSR'd <img> that 404s can miss onError during hydration
  // (the error fires before React attaches the listener). Upgrade to PNG
  // only after a client-side probe proves the frame set exists.
  const [png, setPng] = useState(false);
  useEffect(() => {
    setPng(false);
    const probe = new Image();
    probe.onload = () => setPng(true);
    probe.src = PNG(state);
  }, [state]);
  if (!png) return <SvgFace state={state} />;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={PNG(state)}
      alt={`Tottie ${state}`}
      width={72}
      height={72}
      onError={() => setPng(false)}
    />
  );
}

# Drill Run 3 — habits day 1, corrected harness (2026-11-01)

First run under the corrected method: the agent never hears about
memory. Instructions + full reports flow through MCP remember as
turns; the observer alone curates. Same owner `drill` (multi-project:
splitter history carried), new session `habits-d1`, code in
/tmp/habits. G4 fix live on the server.

## Turns

- T1: "build a CLI habit tracker..." Agent built habits.py (log +
  streaks, fixed habit set, backward-walk streaks with
  today-not-logged grace), verified live with contrast demos.
  Intercepted 4 turns (instruction + build + reasoning + unclear),
  all NEW, 6 clean rows. Artifact re-verified by manager.
- T2: "running counts 3x a week. reading and meditating stay daily."
  Brief card FIRED with the streak semantics unasked. Agent added
  weekly running (Mon-Sun, >=3, no carryover) + fixtures, contrast
  demos. Verified exact. Intercepted; open questions forwarded.
- T3: "sun-sat weeks. and extra runs carry over." Brief card fired
  with the no-carryover rule + Mon-Sun weeks. Agent rewrote
  weekly_streak (Sunday-anchored, surplus carries), contrast proofs
  (Sun-vs-Sat boundary isolated, +2 head start isolated). Verified
  exact. Intercepted.

## Findings

G5 — terse reversals slip UNDER the familiarity floor (NEW, needs
research). "sun-sat weeks. and extra runs carry over." scored
familiar 0.68; the follow-up report turn 0.76. Both < 0.80, so the
contradiction verifier never ran and both landed NEW alongside the
contradicted Mon-Sun rows. Store now holds 6 week-rows, old and new
side by side. Recall currently ranks the new rule #1 (right answer,
by ranking luck, not resolution) with the old rule #2. The G1 fix
only guards reversals similar enough to trip 0.80; short terse
instructions — the most Frans-shaped inputs — sail under it.
Fix directions: cheaper/lower contradiction trigger (NLI is 7ms),
recall-time contradiction detection, length-aware gating.

O5 — multi-project owner works: splitter context briefed into a
habits session caused zero confusion across 3 turns; the agent
never mixed projects. The zombie + fossils ride along as noise the
agents route around (4th consecutive run observing this).

## Verdicts

- Corrected harness (zero memory mentions) works cleanly: 3 turns,
  9 forwarded, all verdicts sane, artifacts verified.
- Memory transfer unasked: T2 and T3 brief cards fired with exactly
  the needed context (streak semantics, no-carryover rule).
- G5 replaces G1 as the top write-path gap: the floor, not the
  verifier, is now the weak link.
- Day-2 probe pending (next turn).

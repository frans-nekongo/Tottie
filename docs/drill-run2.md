# Drill Run 2 — splitter day 3 (2026-10-29)

Same method as run 1 (manager-as-human, fresh subagent per turn,
brief-context + disk only). Continues the splitter on session
`splitter-d3`, owner `drill`, store carried over (14 rows incl. the
G1 zombie + pre-fix Ben-pair fossil). G1 fix live on the server.

## Turns

- D3T1: "yeah do what you suggested." Agent checked memory via recall,
  correctly found NO recorded suggestion (day-2's bar flag lived only
  in its report, never persisted — process lesson: flags must be
  remembered to be recallable; convention updated same turn), inferred
  the newest unhandled fact (Ben drinks at parties, code excludes Ben
  from all alcohol), implemented the party exception with 7 verified
  demos. 5 remembers. Also re-reported the groceries contradiction
  (4th instance) — see G1 verdict.
- D3T2: "add birthday celebration to the party words. and add bar to
  the alcohol list." 2-line change, contrast demos, 3 remembers
  (SUPERSEDE + SKIP + NEW) — see G3.

## Findings

G1-VERIFIED — the fix holds live. The 4th contradiction report
("OPEN CONTRADICTION: brain says groceries default to Anna x2 but
code requires explicit") flowed `contra->0588f071 (polarity-flip
marker)` -> correction lane -> UPDATE. The exact write class that
died 3x in run 1 now lands. Verifier named the right target id.

G1c — active-recall route SHADOWS the verified target (NEW, needs
fix). The contradiction UPDATE journaled onto 51b98eb2 (a row the
agent had just recalled, labile-on-access) instead of the
NLI-verified 0588f071: `apply_candidate` tries the active set before
the correction pool. Consequence, measured: the zombie still
top-hits for "groceries default anna", with the correction surfacing
beside it unresolved — lie first, truth second, no resolution.
Principled fix: explicit verifier target > active > guessed pool
(precision-ordered). Not yet implemented.

G3 — entailment SWALLOWS extensions (NEW, needs research). "ALCOHOL
list now includes bar..." scored familiar 0.84 + NLI entail 0.75 ->
SKIP. The delta (bar is new) died because most content overlapped.
Consequence, measured: recall "which words trigger the alcohol
default" returns 7 hits, zero mention bar anywhere. The real space
has 4 moves (restate / extend / refine / oppose) and NLI's 3 labels
conflate restate+extend. Likely fix shape: NLI for stance +
symbolic token/entity-novelty for coverage (entities in hypothesis
absent from premise -> UPDATE, never SKIP).

O4 — unpersisted flags are unrecallable (process, fixed in
convention): day-2's bar suggestion lived only in the agent report,
so day-3 could not recall it and correctly said so. Harness rule now
includes open questions in the remember convention.

## Verdicts

- G1 observer fix: VERIFIED in the wild. Nothing eaten this run.
- Reversal survival is now 2/2 live (run-1 CLI proof SUPERSEDE +
  run-2 contradiction UPDATE).
- But survival != resolution: G1c leaves the zombie top-hitting and
  G3 loses list-extensions. The drill keeps earning its keep.
- Store is accumulating unresolved tensions (zombie + correction +
  Ben pair side by side). Contradiction-aware RANKING is the visible
  next frontier after G1c/G3.

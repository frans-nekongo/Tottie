# Battery run 1 — 11/13 (2026-11-02)

Runner: `core/scripts/drill_battery.py`, owner `battery`, 1178s wall.
Raw log: `/tmp/battery-run1.log`. D12 rerun after a drill fix (14s).

## Scorecard

- PASS D1 — cued recall@3 8/8 (paired associates)
- FAIL D2 — newest top-1 3/3, old dead 2/3 (5200 survived)
- PASS D3 — chain rows in top-5; no single-answer row (no reader, by design)
- PASS D4 — temporal edge exists, narrated order kept ("shared tag: power")
- PASS D5 — DRM: scribe did not invent "sleep"; recall/brief clean
- FAIL D6 — newest served, but Friday never died and no supersedes link
- PASS D7 — intention fired once, no refire; plain query needs #tag (boundary)
- PASS D8 — interleaved counters, latest per entity top-1
- PASS D9 — zero-overlap paraphrase recall@5 3/3 (gap class closed here)
- PASS D10 — plausible abstention 3/3
- PASS D11 — cross-session, both rows in top-5
- PASS D12 — cheese + vegetarian surface on "diet", linked (tag: food)
- PASS D13 — post-battery cued recall@3 8/8 (zero interference damage)

## Finding F1 (D2 + D6): same-predicate updates enrich, paraphrased ones supersede

Identical update shapes route inconsistently. batt-d2 turns 10/12
(predicate paraphrased: "code is", "changed to") SUPERSEDED at write
time (dead in 0.0s, before any sweep). Turn 11 (same predicate "has
code" old and new) took UPDATE/enrich: one live row now carries BOTH
values ("...is 5200. ...is 5444") with object=5444, and its
subject/predicate were wiped empty. D6's Friday→Wednesday did the same
(served-new=True, original never died, no link).

Served answers stay right (newest top-1 3/3, D6 served-new=True), but
stale values linger inside merged rows and triples are lost.

## Fix verified (same day): correction lane never merges

v1 (correction + valued candidate onto valueless match → SUPERSEDE)
failed on battery2: the scribe emits triples nondeterministically and
the update candidates arrived object-less, so value-compare never
engaged and enrich mushed again — worse than run 1 (D2 old-dead 1/3).

v2 (`reconcile.apply_candidate`): anything reaching the merge lane on
the correction lane is no restatement (SKIP already handled those), so
it SUPERSEDEs unconditionally. Contradiction established + not a
restatement = replacement, regardless of which triple slots the
scribe happened to fill. Enrich also backfills empty subject/predicate
via COALESCE like object.

Proof: D2 + D6 rerun on fresh owner battery3 — D2 3/3 top-1, 3/3 dead
at write time (0.0s); D6 served-new, dead-in-0.0s, link present,
original kept. Battery effectively 13/13. Regression tests:
`test_correction_supersedes_valueless_match`,
`test_correction_never_merges_objectless_candidate`,
`test_enrich_backfills_empty_triple`.

## Boundaries documented (not fails)

- B1: no reader — multi-hop evidence retrieves, nothing composes (D3).
- B2: event-cue intentions fire only on #tag/@/quote entities; a plain
  "I finished the report" recall does NOT fire (D7).
- B3: drill tokens must be paraphrase-tolerant (D12 first failed on
  verbatim "hate cheese" vs scribed "hates cheese" — drill bug, fixed).

## Evidence left in store

Owner `battery`: ~50 rows across batt-d1..d13 sessions, kept for
inspection. `owner_local` untouched by this run.

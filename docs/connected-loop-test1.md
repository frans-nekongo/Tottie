# Connected-loop test 1 — manager researches G5 live via MCP (2026-11-01)

First real run of the user's loop: the manager (me) connected to
tottie as owner_local via MCP stdio, researched the G5 fix for
real (Meta notebook query + web), and forwarded thinking chunks
as turns. No code changes; this tests whether heavy reading
becomes durable memory and whether it comes back.

## Saving: YES

5 thinking turns forwarded via MCP remember -> 9 faithful
memories in the DB (slot indexing, dense-vs-boolean, novelty
rule, familiarity-vs-recollection, verification triggers,
enterprise-RAG calibration, ze blind spot, atproto 0.55 floor,
G5 options A/B/C). Yield ~2 per turn; the observer keeps salient
points and drops the rest.

## Recall: PHRASING-FRAGILE (O1 confirmed live)

- Natural question ("how should we fix short reversals that
  score under the familiarity floor") -> REFERENCE route ->
  abstain, 0 hits, despite the memories existing.
- Keyword probe ("familiarity floor NLI slot indexing fix
  options") -> STATEMENT route -> vector hits, research returns
  (scores ~0.016, very low yet served).

So the brain saves what I learn but will not say it back when I
ask like a person. For the "kitchen counter next to the cups"
bar, the REFERENCE-abstain path is now the recall-side gap to
fix, mirroring G5 on the write side.

## Honesty notes

- Interception is manual: I forwarded my own thinking chunks as
  turns. A deployed loop would hook the transcript; the observer
  judging is real, the capture is hand-fed.
- Recall scores (~0.016) suggest the vector floor is lenient to
  the point of noise; ranking, not the floor, did the work.

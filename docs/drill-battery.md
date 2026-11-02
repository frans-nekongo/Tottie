# Tottie memory battery v1 — design

Date: 2026-11-02. Runner: `core/scripts/drill_battery.py` (owner `battery`,
isolated from `owner_local`). No LLM judge anywhere: every drill scores
judge-free (recall@k by row id, abstain booleans, link existence, liveness
flags, intention firing). Encoding is always raw `/write` turns — never
instructed remembering.

## Why these drills

Two literatures, one battery.

**Cognitive psychology** (how brains are tested): paired associates and
cued recall (cue A, target B must return); A-B/A-D retroactive
interference (change B to D, D must win, B must lose); DRM false memory
(12 associates, never the lure — the lure must NOT be "remembered");
misinformation (misleading update vs original); prospective memory
(remember-to-X-on-Y); serial updating under interference (interleaved
counters); Remember/Know source monitoring (every hit carries its
session/turn provenance); NoLiMa zero-lexical-overlap paraphrase.

**Agent-memory benchmarks** (field guide: mnemoverse, Nov 2026): the
strict-memory family (store-then-recall-later: LoCoMo, LongMemEval,
BEAM) is the only one that tests a persistent store; long-context
tests (NIAH, RULER) can be passed by a big window. LongMemEval's five
abilities — extraction, multi-session reasoning, temporal reasoning,
knowledge updates, abstention — plus BEAM's contradiction resolution
and event ordering map directly onto drills below. The field's hard
lesson is baked in: judge variance moves scores ~40 points, so this
battery leads with recall@k and never calls a judge.

## Drill map

| Drill | Paradigm | Scores |
|---|---|---|
| D1 paired associates | cued recall, 8 code pairs | recall@3 hit rate |
| D2 updates | A-B/A-D interference, 3 changes | newest top-1 + old dead + latency |
| D3 multi-hop | 2-hop chain (Ann→Bex→closing) | both rows in top-5; composition reported absent (no reader by design) |
| D4 temporal | 2 events, 1 turn, narrated out of order | edge exists; direction kept/flipped reported |
| D5 DRM lure | 12 sleep-associates, never "sleep" | scribe must not invent; recall must not assert; brief must not inject |
| D6 misinformation | Friday → Wednesday correction | newest served + supersedes link + original kept with turn-0 provenance |
| D7 prospective | remind-to-call on trigger | registered + fires once + never refires; #tag requirement reported |
| D8 counters | interleaved alpha/beta 1-2-3 | latest per entity top-1 after sweep |
| D9 paraphrase | 3 zero-overlap cues on D1 facts | recall@5 (known gap class) |
| D10 abstention | 3 plausible-but-absent cues | abstain 3/3 |
| D11 cross-session | fact in s1, related in s2 | both in top-5 |
| D12 linked story | cheese + vegetarian (owner's case) | both surface on "diet" + link with reason |
| D13 interference | re-cue all D1 pairs post-battery | delta vs D1 |

D2/D6/D8 trigger `/sweep` then assert steady state (same discipline as
the eval: assert the state, not the heartbeat timing). D13 measures
what the battery itself cost D1: proactive/retroactive interference
from ~40 intervening turns.

## Honesty rules for this battery

- A drill that fails documents a boundary; it is never reworded into passing.
- Encoding misses are system misses (single attempt, no resends).
- Reach items are labeled reach before running, not after failing.
- Results live in `docs/drill-battery-runN.md` with the raw log path.

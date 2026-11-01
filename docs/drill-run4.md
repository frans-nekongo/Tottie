# Drill Run 4 — readlog + updater/upgraded retrieval (2026-11-01)

First drill on the multi-agent stack (updater, linker, ranker, entity
leg, async accept). Same corrected method: agent never hears about
memory. Owner `drill` (third project alongside splitter + habits),
sessions readlog-d1 (build) and readlog-d2 (fresh probe).

## Turns

- T1: build CLI reading log (add/list/done, JSON store). Verified
  live incl. done-missing exit 1. Intercepted.
- T2: add stats (total/read/pages-read-only). Verified incl. empty
  store edge. Intercepted.
- T3: terse reversal "pages count everything now, read or not."
  Agent rewrote to Total pages 740. Verified. Intercepted.
- Updater sweep on drill: retired_contra 1 — the old pages-read
  rule retired newest-wins under the new all-books rule. The
  G5-class terse reversal now resolves in background.
- T4 (fresh agent, readlog-d2): "add report with per-book lines +
  stats totals". Output 740, correct current rule. Verified.

## Findings

U1 — updater closes the G5 loop live. The terse reversal sailed
under the write-path floor as before, but the sweep caught it
afterward (symmetric-contra, newest-wins). Write path + background
sweep together cover what neither covers alone.

U2 — numeric state escapes NLI. Brief card for readlog-d2 carried
a stale "pages read 412" snapshot alongside the current 740 rule:
number-vs-number pairs read neutral, never contra, so the updater
passes over them. Needs slot-aware numeric comparison (entity +
predicate match with differing numbers = update).

U3 — mixed rows still leak. The habits.py Mon-Sun row (stale week
clause + live daily-streak rules in one row) briefed into a
readlog session. Splitting mixed rows remains the open gap.

O6 — brief card fired exactly right for a fresh session: current
pages rule, the reversal event, add-command schema, project
structure — all unasked. Multi-project owner (3 projects) still
routes cleanly.

## Honesty note

T4's behavioral pass (740) does NOT isolate memory: the agent
could read the current rule from readlog.py itself. The memory
evidence is the brief card firing correctly, not the agent output.
Future probes need a fact that lives ONLY in conversation (e.g. a
naming decision) to truly isolate recall.

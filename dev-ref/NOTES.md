# dev-ref-1 — REFERENCE referent resolution (read path)

## Gap
REFERENCE cues ("use that DB we discussed") classify, then fall through to
general recall. No resolution happens.

## Design (decided 2026-10-29)
When `cue.type == REFERENCE` on the ranked branch:
1. Resolve referent from last-10 live session episodic rows (logical-turn
   desc; never created_at — concurrency doctrine; null turns last).
2. Evidence tiers: explicit entities (#/@/quotes, w=3, must-match) >
   definite nouns (that-N / the-same-N, w=2, must-match) > soft content
   words (w=1, shell verbs stripped: use/discussed/mentioned/same/...).
3. Selection: highest score; ties salience then recency. All-zero soft-only
   queries fall back to most recent (pronoun baseline). Empty window or an
   unmatched must-match constraint -> None -> honest abstain (no fallthrough
   to general recall).
4. Recall against referent: expanded query (query + referent content) drives
   vector/lexical legs; referent tags join the assoc leg; confidence coverage
   runs on the expanded query. Story narrates `referent <id8> (<match>)`;
   output carries `referent {id, summary, match}`.
5. Replay precedence unchanged (recency markers still replay). All other cue
   types byte-identical: no shared code path touched.

## Why this mechanism
- "We discussed" lives in session episodes — that is the window.
- Definite descriptions ("that DB") denote; guessing when they match nothing
  would confabulate, so they abstain.
- Bare pronouns ("do the same") carry no content; recency is the standard
  linguistic baseline (most salient = last mentioned).
- Expanded-query recall reuses the calibrated legs + confidence floor instead
  of inventing a parallel ranker.

## Classifier
cues.py untouched: bare "it"/"they" do NOT classify REFERENCE today, and
adding pronoun detection would re-route QUESTION/STATEMENT queries (breaking
the no-behavior-change requirement). REFERENCE = that-N / the same /
we discussed / you mentioned.

## Tests (core/tests/test_recall.py)
- referent resolved by overlap (beats recency), answer served, referent in output
- empty session -> honest abstain (hits [], card None, story narrates)
- unmatched "that N" definite in non-empty session -> abstain (no guessing)

---
# dev-ref-2 — handoff: plural referents + tie-break turn naming (2026-10-29)

## Inherited verdict
- All 4 tests green on arrival; design in NOTES.md matched the code.
- Nothing broken. Singular selection, abstention, and replay precedence kept
  byte-identical (same scoring, same labels, same eff_query for singular).

## What changed (core/app/agents/retrieve.py only; cues.py untouched)
- `_resolve_referent` -> `_resolve_referents(db,..., plural)` returning
  (referents, tie_broke). Singular path = same winner, same match strings.
- Plural detection (`_is_plural_reference`: they/them/their/those/these)
  lives in retrieve.py, NOT the classifier — bare pronouns keep their cue
  path (inherited no-re-routing constraint); they resolve plurally inside
  REFERENCE queries ("use them as we discussed").
- Plural returns ALL matching recent candidates (must-match filters still
  apply; soft-only keeps score>0; zero-evidence keeps whole window,
  most-recent-first). Expanded query joins all contents; tags union.
- those/these-N captured as must-match definites (label those-N/these-N);
  `_referent_matches` folds plurals ("DBs" matches stored "DB").
- Tie = recency decided the primary (shared score+salience, or fallback
  with 2+ contenders). Story names it: singular
  `referent <id8> (<match>; tie-break turn N)`; plural
  `referents <ids> (N matches; tie-break|primary turn N)`.
- Output: `referent` gains `turn`; new uniform `referents` list
  (abstain -> []). Non-REFERENCE outputs untouched (no new keys).

## New tests (4)
- plural "those DBs" -> both DB rows, most-recent-first, lunch excluded,
  both in hits, story "2 matches; tie-break turn 1"
- plural pronouns ("they"/"them", zero-evidence) -> whole window, recency
  order, story names turn 1
- singular tie (equal score+salience) -> most recent turn, story names it
- plural unmatched definite ("those DBs", garden-only) -> honest abstain

## Gate
- `pytest core/tests/test_recall.py -k reference`: 8 passed
- `pytest core/tests/test_recall.py core/tests/test_briefing.py -k "not live"`: 40 passed, 1 deselected
- `pytest core/tests/test_cues.py`: 11 passed (untouched, sanity)

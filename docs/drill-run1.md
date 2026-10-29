# Drill Run 1 — roommate expense splitter (2026-10-29)

Method: manager plays the human (Frans: terse, never restates); fresh
subagent per turn plays the developer (Muse: builds, persists via
`tottie.py remember`, runs on pasted brief-context + code on disk only).
Dummy project is fictional to us, real to the agent. Every claim below
was re-verified by the manager (reran demos, queried the DB, read the
event log). Owner `drill`, sessions `splitter-d1` (turns 0–3) and
`splitter-d2` (day-2 probe).

## Turns

- T0: "build a CLI expense splitter for roommates. Anna, Ben, Cara…"
  Built `/tmp/roommates/splitter.py` (add/list/balances/owes, equal
  split, JSON). 4 memories stored, all retrieve at 0.98 on lexical
  probe. Brief for T1: card abstained (0.187), new-since carried all 4.
- T1: "add unequal shares. anna counts double on groceries…"
  Added `--shares`, groceries→Anna-x2 auto-default. 3 memories stored.
  Verified live. Brief for T2: card abstained (0.361), new-since 6/6.
- T2: "ben doesnt drink. alcohol splits exclude him. and kill the
  groceries auto-default. anna-double only when asked, never automatic."
  Code: alcohol→Anna+Cara default added, groceries default removed,
  verified live. Store: 2 of 3 writes landed; the reversal
  ("Groceries auto-default is killed…") was DROPPED — see G1.
- T3: "add settle-up…" Built `settle` + `payments.json`, verified live.
  Agent caught the brain-vs-code contradiction and reported it; that
  report was also dropped — see G1 (2nd instance). 2 of 3 writes landed.
- Day 2 (new session, zero restatement): "add cara's birthday dinner
  at the bar, anna paid 90." Brief card FIRED (0.565, COMMAND mode)
  with the Ben rule, word list, override policy. Agent added equal
  3-way (bar not in word list), explicitly flagged the ambiguity,
  remembered the decision. PASS on memory transfer (details below).
  Its 2nd contradiction report was dropped — G1 (3rd instance).

Final store: 12 rows, 3 writes silently dropped (all G1 instances).

## Findings

G1 — familiarity gate eats unmarked reversals (REPRODUCED 3x).
A write that contradicts a stored row but carries no explicit
correction marker ("actually…", "no wait…") is judged "already known"
(familiar 0.80/0.83/0.86 ≥ 0.80) and SKIPped with n=0. The stale row
stays live and keeps surfacing as top hit (0.98). Worse: reports
*about* the error ("Contradiction: brain says X but code says Y") are
eaten the same way — the system cannot hear it is wrong. In real use
this is exactly how "kill that default" becomes a zombie truth.
Needs contradiction/opposition detection in the observer, not just
marked-correction patterns. Research item, not yet fixed.

O1 — natural question phrasing abstains: "what did we decide about
the splitter" → 0.31 abstain; keyword probe on identical content →
0.98 hit. QUESTION-mode calibration data point.
O2 — brief card abstained at 0.404 while the recall floor is 0.35;
card path uses a stricter rule. Confirm intended.

## Fix (same day, post-drill)

Research (META notebook + web + Mem0) converged on a two-stage filter:
familiarity is a candidate gate, never a drop gate; an NLI verifier
labels the pair entail/neutral/contradict. Implemented:

- `core/app/nli.py`: ONNX DeBERTa-v3-small (int8, 160MB, `local LLMS/`,
  no torch), premise=stored row, hypothesis=incoming turn. Auto-fetches
  weights once; any failure degrades OPEN (fall through to scribe).
- `cues.polarity_flip`: explicit reversal acts (kill/never/stop/...) —
  fires only inside the familiar branch. Bare negations deliberately
  excluded (measured: NLI judges them correctly, lexicon cannot).
- `observer._contradiction`: contradict -> correction lane with the
  verified target id (works across days, no pool guessing); entail ->
  legacy SKIP+rehearse; neutral -> normal scribe. `TOTTIE_NLI_ENABLED=0`
  restores byte-identical old behavior (film-week hatch).
- `reconcile`: correction-lane matches compare (predicate, object)
  jointly — second G1 layer found live: object-only compare SKIPped
  "does not drink" -> "drinks" (both "alcohol") even after the observer
  fix. General path untouched.
- Pins: `tests/test_nli.py` (7: lexicon, live NLI labels, routing, 2x
  e2e SUPERSEDE incl. flag-off sensitivity twin, dup-SKIP) +
  2 reconcile predicate pins. Full suite 171 green, 6/6 pipeline-live.
- Incidental: `test_write_correction_journals` over-pinned UPDATE but
  the live LLM sometimes scribes SP (-> SUPERSEDE, correct on base
  too). Now pins invariants (1 live row, Wednesday current, Friday
  kept, recall serves it) under either op.
- Measured quirks: int8 NLI reads far-apart pairs as contradiction
  (unreachable: gate only forwards >= 0.80 cosine); NLI threshold 0.70
  holds (true contradictions hit 1.00).

## Verdicts

- Product claim "brain gives context back unasked": DEMONSTRATED.
  Day-2 agent reasoned from yesterday's Ben rule, word list, override
  policy, and the groceries contradiction with zero restatement.
- Agent followed code over memory-spirit on the bar edge (literal word
  list won, ambiguity loudly flagged). Correct developer behavior; the
  exposed gap is the code's word list, not the memory.
- Drill method vindicated: G1 is invisible to the pytest suite (all
  green) and only surfaced through real multi-turn work with a
  reversal. This is the class of bug the method exists to catch.

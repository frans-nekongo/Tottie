## outcome 2

What I added:
- `streak` command: `habits streak [name]` prints consecutive-day streaks —
  one habit when a name is given (`Name: streak N`), all habits otherwise.
  Unknown habit exits 1 with `error: unknown habit: <name>` on stderr;
  empty store prints `no habits yet`.
- `list` now shows each habit's streak: `[x] Read (3 day(s) done, streak 3)`.
- Store helpers in `habits/store.py`: `streak_for(done, today=None)` (pure
  consecutive-day counter) and `habit_streak(path, name)` (raises KeyError
  for unknown habits). `list_habits()` gains an additive `"streak"` key.
- 7 new tests (streak unit cases, streak single/all/unknown/empty, list
  shows streak, habit_streak API + KeyError).

Decision: streak counts back from today if done today, else from yesterday
— a habit done yesterday but not yet today keeps its streak; a gap before
yesterday means 0. Malformed and future dates are ignored. Schema unchanged
(sorted ISO date lists).

Existing files touched:
- habits/store.py (streak_for, habit_streak, streak in list_habits)
- habits/cli.py (streak subcommand, streak in list output)
- habits/__init__.py (export streak_for, habit_streak)
- habits/test_habits.py (7 new tests + backfill helper)

Final pytest result: 17 passed in 0.47s (10 phase-1 + 7 new), via
`uvx --with pytest pytest habits/test_habits.py` from tottie/worker-comet.

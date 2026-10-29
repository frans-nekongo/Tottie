## outcome 1

Phase 1 complete: stdlib-only Python CLI habit tracker with JSON file store.

Exact file paths (relative to repo root `portals/`):
- `tottie/worker-comet/habits/__init__.py` — package exports
- `tottie/worker-comet/habits/__main__.py` — `python -m habits` entry point
- `tottie/worker-comet/habits/cli.py` — argparse CLI, exit codes
- `tottie/worker-comet/habits/store.py` — JSON load/save plus habit logic
- `tottie/worker-comet/habits/test_habits.py` — pytest suite (10 tests)

Command names:
- `add <name>` — add a habit; exit 1 if it already exists or name is blank
- `check <name>` — mark the habit done for today (idempotent); exit 1 if unknown
- `list` — list habits with `[x]`/`[ ]` for today's status plus total days done

Global option `--store/-s` overrides the JSON path; otherwise `$HABITS_FILE`
or `~/.habits.json` is used. Usage: `python -m habits [--store FILE] <command>`.

JSON schema:
```json
{
  "version": 1,
  "habits": {
    "<name>": {"created": "YYYY-MM-DD", "done": ["YYYY-MM-DD", "..."]}
  }
}
```

Design decision and why:
- Completion dates are stored as a sorted list of ISO date strings per habit,
  not booleans or nested objects. This keeps the schema flat and human-editable,
  makes "done today" a simple membership test, and preserves full history so
  streaks or stats can be added later without migration.

Final pytest result line:
- `10 passed in 0.09s` (run: `uv run --with pytest python -m pytest habits/test_habits.py -v`, pytest 9.2.0, Python 3.12.15)

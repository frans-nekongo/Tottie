"""Habit tracker store: JSON file backend (stdlib only)."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

SCHEMA_VERSION = 1

DEFAULT_STORE = Path(os.environ.get("HABITS_FILE", Path.home() / ".habits.json"))


def default_store_path() -> Path:
    return Path(os.environ.get("HABITS_FILE", str(DEFAULT_STORE)))


def load(path: Path | str) -> dict:
    path = Path(path)
    if not path.exists():
        return {"version": SCHEMA_VERSION, "habits": {}}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "habits" not in data or not isinstance(data["habits"], dict):
        return {"version": SCHEMA_VERSION, "habits": {}}
    return data


def save(path: Path | str, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def add_habit(path: Path | str, name: str) -> bool:
    """Add a habit. Returns False if it already exists."""
    name = name.strip()
    if not name:
        raise ValueError("habit name must not be empty")
    data = load(path)
    if name in data["habits"]:
        return False
    data["habits"][name] = {"created": date.today().isoformat(), "done": []}
    save(path, data)
    return True


def check_habit(path: Path | str, name: str, day: str | None = None) -> bool:
    """Mark a habit done for today (or `day`). Returns False if already marked."""
    data = load(path)
    if name not in data["habits"]:
        raise KeyError(f"unknown habit: {name!r}")
    day = day or date.today().isoformat()
    done = data["habits"][name].setdefault("done", [])
    if day in done:
        return False
    done.append(day)
    done.sort()
    save(path, data)
    return True


def streak_for(done: list[str], today: date | None = None) -> int:
    """Count consecutive-day streak ending today (or yesterday if today is not done).

    A habit done yesterday but not yet today keeps its streak; a habit with a
    gap before yesterday has streak 0.
    """
    today = today or date.today()
    days: set[date] = set()
    for d in done:
        try:
            parsed = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            continue
        if parsed <= today:
            days.add(parsed)
    if today not in days:
        today = today - timedelta(days=1)
    streak = 0
    while today in days:
        streak += 1
        today -= timedelta(days=1)
    return streak


def habit_streak(path: Path | str, name: str) -> int:
    """Return the current streak for one habit. Raises KeyError if unknown."""
    data = load(path)
    if name not in data["habits"]:
        raise KeyError(f"unknown habit: {name!r}")
    return streak_for(data["habits"][name].get("done", []))


def list_habits(path: Path | str) -> dict:
    """Return {name: {"created": str, "done": [dates], "done_today": bool, "streak": int}}."""
    data = load(path)
    today = date.today().isoformat()
    return {
        name: {
            "created": info.get("created", ""),
            "done": list(info.get("done", [])),
            "done_today": today in info.get("done", []),
            "streak": streak_for(info.get("done", [])),
        }
        for name, info in sorted(data["habits"].items())
    }

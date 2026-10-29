"""Pytest suite proving the habit tracker CLI commands."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from habits.cli import main
from habits.store import check_habit, habit_streak, list_habits, streak_for


def run_cli(store: Path, *args: str):
    return main(["--store", str(store), *args])


def test_add_creates_habit(tmp_path, capsys):
    store = tmp_path / "habits.json"
    assert run_cli(store, "add", "Read") == 0
    out = capsys.readouterr().out
    assert "added: Read" in out
    data = json.loads(store.read_text())
    assert "Read" in data["habits"]
    assert data["habits"]["Read"]["done"] == []


def test_add_duplicate_fails(tmp_path, capsys):
    store = tmp_path / "habits.json"
    assert run_cli(store, "add", "Run") == 0
    capsys.readouterr()
    assert run_cli(store, "add", "Run") == 1
    assert "already exists" in capsys.readouterr().out


def test_add_empty_name_rejected(tmp_path, capsys):
    store = tmp_path / "habits.json"
    assert run_cli(store, "add", "   ") == 1


def test_check_marks_today_done(tmp_path, capsys):
    store = tmp_path / "habits.json"
    run_cli(store, "add", "Meditate")
    capsys.readouterr()
    assert run_cli(store, "check", "Meditate") == 0
    assert "done today" in capsys.readouterr().out
    data = json.loads(store.read_text())
    assert date.today().isoformat() in data["habits"]["Meditate"]["done"]


def test_check_twice_same_day_is_idempotent(tmp_path, capsys):
    store = tmp_path / "habits.json"
    run_cli(store, "add", "Walk")
    run_cli(store, "check", "Walk")
    capsys.readouterr()
    assert run_cli(store, "check", "Walk") == 0
    assert "already done today" in capsys.readouterr().out
    data = json.loads(store.read_text())
    assert data["habits"]["Walk"]["done"].count(date.today().isoformat()) == 1


def test_check_unknown_habit_fails(tmp_path, capsys):
    store = tmp_path / "habits.json"
    assert run_cli(store, "check", "Nope") == 1
    assert "unknown habit" in capsys.readouterr().err


def test_list_shows_status(tmp_path, capsys):
    store = tmp_path / "habits.json"
    run_cli(store, "add", "Read")
    run_cli(store, "add", "Run")
    run_cli(store, "check", "Read")
    capsys.readouterr()
    assert run_cli(store, "list") == 0
    out = capsys.readouterr().out
    assert "[x] Read" in out
    assert "[ ] Run" in out


def test_list_empty_store(tmp_path, capsys):
    store = tmp_path / "habits.json"
    assert run_cli(store, "list") == 0
    assert "no habits yet" in capsys.readouterr().out


def test_list_habits_api_marks_done_today(tmp_path):
    store = tmp_path / "habits.json"
    run_cli(store, "add", "Yoga")
    run_cli(store, "check", "Yoga")
    habits = list_habits(store)
    assert habits["Yoga"]["done_today"] is True


def test_cli_via_subprocess_module(tmp_path):
    store = tmp_path / "habits.json"
    pkg_root = Path(__file__).resolve().parent.parent
    env = {"HABITS_FILE": str(store), "PATH": "/usr/bin:/bin"}
    r = subprocess.run(
        [sys.executable, "-m", "habits", "add", "Swim"],
        capture_output=True, text=True, cwd=pkg_root, env=env,
    )
    assert r.returncode == 0, r.stderr
    r = subprocess.run(
        [sys.executable, "-m", "habits", "list"],
        capture_output=True, text=True, cwd=pkg_root, env=env,
    )
    assert r.returncode == 0, r.stderr
    assert "Swim" in r.stdout


def backfill(store: Path, name: str, days_ago: list[int]):
    from datetime import timedelta

    today = date.today()
    for n in days_ago:
        check_habit(store, name, (today - timedelta(days=n)).isoformat())


def test_streak_counts_consecutive_days(tmp_path):
    from datetime import timedelta

    assert streak_for([]) == 0
    today = date.today()

    def iso(n: int) -> str:
        return (today - timedelta(days=n)).isoformat()

    assert streak_for([iso(0)]) == 1
    assert streak_for([iso(0), iso(1), iso(2)]) == 3
    assert streak_for([iso(0), iso(2)]) == 1  # gap breaks streak
    assert streak_for([iso(1), iso(2)]) == 2  # done yesterday, not yet today
    assert streak_for([iso(3)]) == 0  # last done 3 days ago


def test_streak_command_single_habit(tmp_path, capsys):
    store = tmp_path / "habits.json"
    run_cli(store, "add", "Read")
    backfill(store, "Read", [0, 1, 2])
    capsys.readouterr()
    assert run_cli(store, "streak", "Read") == 0
    assert "Read: streak 3" in capsys.readouterr().out


def test_streak_command_all_habits(tmp_path, capsys):
    store = tmp_path / "habits.json"
    run_cli(store, "add", "Read")
    run_cli(store, "add", "Run")
    backfill(store, "Read", [0, 1])
    capsys.readouterr()
    assert run_cli(store, "streak") == 0
    out = capsys.readouterr().out
    assert "Read: streak 2" in out
    assert "Run: streak 0" in out


def test_streak_unknown_habit_fails(tmp_path, capsys):
    store = tmp_path / "habits.json"
    assert run_cli(store, "streak", "Nope") == 1
    assert "unknown habit" in capsys.readouterr().err


def test_streak_empty_store(tmp_path, capsys):
    store = tmp_path / "habits.json"
    assert run_cli(store, "streak") == 0
    assert "no habits yet" in capsys.readouterr().out


def test_list_shows_streak(tmp_path, capsys):
    store = tmp_path / "habits.json"
    run_cli(store, "add", "Read")
    backfill(store, "Read", [0, 1, 2])
    capsys.readouterr()
    assert run_cli(store, "list") == 0
    out = capsys.readouterr().out
    assert "streak 3" in out


def test_habit_streak_api(tmp_path):
    store = tmp_path / "habits.json"
    run_cli(store, "add", "Yoga")
    backfill(store, "Yoga", [0])
    assert habit_streak(store, "Yoga") == 1
    with pytest.raises(KeyError):
        habit_streak(store, "Nope")

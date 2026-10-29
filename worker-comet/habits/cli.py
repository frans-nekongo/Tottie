"""Habit tracker CLI (stdlib only): add, check, list, streak."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .store import add_habit, check_habit, default_store_path, habit_streak, list_habits


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="habits", description="Simple habit tracker")
    p.add_argument(
        "--store", "-s", default=None, help="Path to JSON store (default: $HABITS_FILE or ~/.habits.json)"
    )
    sub = p.add_subparsers(dest="command", required=True)

    pa = sub.add_parser("add", help="Add a new habit")
    pa.add_argument("name", help="Habit name")

    pc = sub.add_parser("check", help="Mark a habit done for today")
    pc.add_argument("name", help="Habit name")

    sub.add_parser("list", help="List habits and today's status")

    ps = sub.add_parser("streak", help="Show consecutive-day streaks")
    ps.add_argument("name", nargs="?", default=None, help="Habit name (default: all habits)")
    return p


def resolve_store(args) -> Path:
    if args.store:
        return Path(args.store)
    return default_store_path()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = resolve_store(args)

    if args.command == "add":
        try:
            created = add_habit(store, args.name)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if not created:
            print(f"habit already exists: {args.name}")
            return 1
        print(f"added: {args.name}")
        return 0

    if args.command == "check":
        try:
            marked = check_habit(store, args.name)
        except KeyError:
            print(f"error: unknown habit: {args.name}", file=sys.stderr)
            return 1
        if not marked:
            print(f"already done today: {args.name}")
            return 0
        print(f"done today: {args.name}")
        return 0

    if args.command == "list":
        habits = list_habits(store)
        if not habits:
            print("no habits yet")
            return 0
        for name, info in habits.items():
            mark = "x" if info["done_today"] else " "
            total = len(info["done"])
            print(f"[{mark}] {name} ({total} day(s) done, streak {info['streak']})")
        return 0

    if args.command == "streak":
        if args.name is not None:
            try:
                streak = habit_streak(store, args.name)
            except KeyError:
                print(f"error: unknown habit: {args.name}", file=sys.stderr)
                return 1
            print(f"{args.name}: streak {streak}")
            return 0
        habits = list_habits(store)
        if not habits:
            print("no habits yet")
            return 0
        for name, info in habits.items():
            print(f"{name}: streak {info['streak']}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

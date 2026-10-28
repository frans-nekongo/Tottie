#!/usr/bin/env python
"""tottie CLI: the agent's hands. Stdlib only.

  ./venv/bin/python scripts/tottie.py brief --owner frans --session s1 [--text "..."] [--since 0]
  ./venv/bin/python scripts/tottie.py remember --owner frans --session s1 --turn 0 [--trust tool] "text to keep"
  ./venv/bin/python scripts/tottie.py recall --owner frans --session s1 --text "question?" [--k 8]
  ./venv/bin/python scripts/tottie.py sleep --owner frans --session s1

Reads TOTTIE_CORE_URL / TOTTIE_API_TOKEN from env (or Tottie/.env).
(cwd=core.)
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path


def _load_dotenv(path: Path | None = None) -> None:
    """Honor the docstring: Tottie/.env fills what the environment lacks.
    Stdlib only. Real environment always wins over the file."""
    env_file = path or Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _config() -> tuple[str, str]:
    _load_dotenv()
    return (
        os.environ.get("TOTTIE_CORE_URL", "http://127.0.0.1:8765"),
        os.environ.get("TOTTIE_API_TOKEN", ""),
    )


def _req(method, path, body=None):
    core, token = _config()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        core + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}")
        except ValueError:
            detail = {}
        return e.code, detail


def _fail(msg):
    print(f"tottie: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(prog="tottie")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brief", help="ambient surface for one agent turn")
    b.add_argument("--owner", default="owner_local")
    b.add_argument("--session", required=True)
    b.add_argument("--text", default=None)
    b.add_argument("--since", type=int, default=0)
    r = sub.add_parser("remember", help="hand the Scribe a turn")
    r.add_argument("--owner", default="owner_local")
    r.add_argument("--session", required=True)
    r.add_argument("--turn", type=int, required=True)
    r.add_argument("--trust", default="user_direct",
                   choices=["user_direct", "tool", "web", "model_inferred"])
    r.add_argument("text")
    q = sub.add_parser("recall", help="cue-typed recall + Context Card")
    q.add_argument("--owner", default="owner_local")
    q.add_argument("--session", required=True)
    q.add_argument("--text", required=True)
    q.add_argument("--k", type=int, default=None)
    s = sub.add_parser("sleep", help="run consolidation now")
    s.add_argument("--owner", default="owner_local")
    s.add_argument("--session", required=True)
    rl = sub.add_parser("relink", help="recompute links for old rows (offline)")
    rl.add_argument("--owner", default="owner_local")
    args = ap.parse_args()
    _, token = _config()
    if not token and args.cmd != "relink":
        _fail("TOTTIE_API_TOKEN is empty")
    if args.cmd == "brief":
        code, out = _req("POST", "/briefing", {
            "owner": args.owner, "session_id": args.session,
            "text": args.text, "since_event_id": args.since,
        })
        if code != 200:
            _fail(f"/briefing -> {code} {out}")
        print(out["briefing"])
        print(f"\n[event {out['event_id']}] "
              f"confidence={out['confidence']} abstain={out['abstain']}")
    elif args.cmd == "remember":
        code, out = _req("POST", "/write", {
            "text": args.text, "session_id": args.session,
            "turn": args.turn, "owner": args.owner,
            "source": {"trust": args.trust},
        })
        if code != 202:
            _fail(f"/write -> {code} {out}")
        print(f"queued {out['event_id']} ({out['mode']})")
    elif args.cmd == "recall":
        body = {"query": args.text, "session_id": args.session,
                "owner": args.owner}
        if args.k:
            body["k"] = args.k
        code, out = _req("POST", "/recall", body)
        if code != 200:
            _fail(f"/recall -> {code} {out}")
        print(out["card"] or "(abstained — nothing relevant)")
        print(f"\nconfidence={out['confidence']} abstain={out['abstain']} "
              f"mode={out['mode']} story={out['story']}")
    elif args.cmd == "sleep":
        code, out = _req("POST", "/consolidate", {
            "owner": args.owner, "session_id": args.session,
        })
        if code != 200:
            _fail(f"/consolidate -> {code} {out}")
        print(f"{out['episodes_replayed']} episodic -> "
              f"{out['semantic_written']} semantic; "
              f"{out['ranked_out']} ranked out")
    elif args.cmd == "relink":
        import asyncio

        sys.path.insert(0, ".")
        from app.agents import relink as rl_agent
        from app.config import get_settings
        from app.db import Database

        async def _run():
            db = Database(get_settings())
            await db.open()
            try:
                return await rl_agent.relink(db, args.owner)
            finally:
                await db.close()

        made = asyncio.run(_run())
        print(f"relinked {made['temporal']} temporal, {made['tag']} tag")


if __name__ == "__main__":
    main()

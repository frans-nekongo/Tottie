#!/usr/bin/env python
"""tottie CLI: the agent's hands. Stdlib only.

  ./venv/bin/python scripts/tottie.py brief --owner frans --session s1 [--text "..."] [--since 0]
  ./venv/bin/python scripts/tottie.py remember --owner frans --session s1 --turn 0 "text to keep"
  ./venv/bin/python scripts/tottie.py sleep --owner frans --session s1

Reads TOTTIE_CORE_URL / TOTTIE_API_TOKEN from env (or Tottie/.env).
(cwd=core.)
"""
import argparse
import json
import os
import sys
import urllib.request

CORE = os.environ.get("TOTTIE_CORE_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("TOTTIE_API_TOKEN", "")


def _req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        CORE + path, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}",
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
    r.add_argument("text")
    s = sub.add_parser("sleep", help="run consolidation now")
    s.add_argument("--owner", default="owner_local")
    s.add_argument("--session", required=True)
    args = ap.parse_args()
    if not TOKEN:
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
            "source": {"trust": "user_direct"},
        })
        if code != 202:
            _fail(f"/write -> {code} {out}")
        print(f"queued {out['event_id']} ({out['mode']})")
    elif args.cmd == "sleep":
        code, out = _req("POST", "/consolidate", {
            "owner": args.owner, "session_id": args.session,
        })
        if code != 200:
            _fail(f"/consolidate -> {code} {out}")
        print(f"{out['episodes_replayed']} episodic -> "
              f"{out['semantic_written']} semantic; "
              f"{out['ranked_out']} ranked out")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Tail a Muse session transcript and forward turns to tottie automatically.

Watches session.jsonl for new records, extracts user prompts (started) and
assistant conclusions (assistant_message_committed), scrubs secrets, and
POSTs each as a turn to the core /write endpoint. No per-turn action needed.

Usage:
  TOTTIE_API_TOKEN=... ./session_watch.py [--backfill N] [--once]

State (byte offset + turn counter) lives next to the log path in /tmp so a
restart never replays the whole history. Logs are read-only; this script
never modifies the session store.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request

SESSION_ID = os.environ.get(
    "MUSE_SESSION_ID", "01a1783d-40f9-7552-8e6f-6cdf013c5a7e"
)
LOG_PATH = os.environ.get(
    "MUSE_SESSION_LOG",
    os.path.expanduser(
        "~/.local/share/muse/sessions/2026/10/26/%s/session.jsonl" % SESSION_ID
    ),
)
CORE_URL = os.environ.get("TOTTIE_CORE_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("TOTTIE_API_TOKEN", "changeme-local-token")
OWNER = os.environ.get("TOTTIE_OWNER", "owner_local")
STATE_PATH = "/tmp/tottie-watch-%s.json" % SESSION_ID[:8]

SECRET_RES = [
    re.compile(r"LLM_[A-Za-z0-9_\-]+"),
    re.compile(r"[Bb]earer\s+[A-Za-z0-9_\-\.]+"),
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
]
MIN_CHARS = 40
MAX_CHARS = 15000


def scrub(text: str) -> str:
    for rx in SECRET_RES:
        text = rx.sub("[REDACTED]", text)
    return text


def load_state() -> dict:
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"offset": 0, "turn": 0, "seen": []}


def save_state(state: dict) -> None:
    state["seen"] = state.get("seen", [])[-500:]
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE_PATH)


def extract(line: str):
    """Return (record_id, kind, text) or None."""
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    payload = rec.get("payload") or {}
    event = payload.get("event") or {}
    kind = event.get("kind")
    if kind == "assistant_message_committed":
        text = event.get("text") or ""
        if len(text.strip()) >= MIN_CHARS:
            return rec.get("id"), "assistant", text.strip()[:MAX_CHARS]
    elif kind == "started" and payload.get("kind") == "run":
        prompt = event.get("prompt") or ""
        if len(prompt.strip()) >= MIN_CHARS:
            return rec.get("id"), "user", prompt.strip()[:MAX_CHARS]
    return None


def post_turn(text: str, trust: str, session: str, turn: int) -> str:
    body = json.dumps(
        {
            "text": text,
            "session_id": session,
            "turn": turn,
            "owner": OWNER,
            "source": {"trust": trust, "origin": "session_watch"},
        }
    ).encode()
    req = urllib.request.Request(
        CORE_URL.rstrip("/") + "/write",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % TOKEN,
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode()[:200]


def scan(fh, state: dict, session: str, backfill: int) -> int:
    fh.seek(state.get("offset", 0))
    pending: list[tuple[str, str, str]] = []
    for line in fh:
        item = extract(line)
        if item and item[0] not in state.get("seen", []):
            pending.append(item)
    if backfill >= 0:
        pending = pending[-backfill:] if backfill else []
    # Normal tail mode: backfill < 0 means take everything new.
    sent = 0
    for rid, kind, text in pending if backfill >= 0 else pending:
        trust = "user_direct" if kind == "user" else "model_inferred"
        try:
            post_turn(scrub(text), trust, session, state.get("turn", 0))
        except Exception as exc:  # noqa: BLE001 - daemon must not die
            print("forward failed: %s" % exc, flush=True)
            break
        state["turn"] = state.get("turn", 0) + 1
        state.setdefault("seen", []).append(rid)
        sent += 1
        print("forwarded %s turn=%d chars=%d" % (kind, state["turn"], len(text)), flush=True)
    state["offset"] = fh.tell()
    save_state(state)
    return sent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=-1,
                    help="N last pending turns only; -1 = all new; 0 = just mark offset")
    ap.add_argument("--once", action="store_true", help="single pass then exit")
    ap.add_argument("--session", default="muse-%s" % SESSION_ID[:8])
    args = ap.parse_args()

    if not os.path.exists(LOG_PATH):
        print("no session log at %s" % LOG_PATH)
        return 1
    state = load_state()
    # First ever run with no offset: start at end unless backfill requested.
    if state.get("offset", 0) == 0 and args.backfill < 0 and not args.once:
        state["offset"] = os.path.getsize(LOG_PATH)
    sent_total = 0
    with open(LOG_PATH) as fh:
        sent_total += scan(fh, state, args.session, args.backfill)
        if args.once:
            print("once: sent %d" % sent_total)
            return 0
        print("watching %s -> %s (owner=%s session=%s)" % (LOG_PATH, CORE_URL, OWNER, args.session), flush=True)
        while True:
            time.sleep(5)
            # Log rotation / truncation guard.
            try:
                size = os.path.getsize(LOG_PATH)
            except OSError:
                continue
            if size < state.get("offset", 0):
                state["offset"] = 0
            sent_total += scan(fh, state, args.session, -1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

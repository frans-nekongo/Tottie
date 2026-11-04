#!/usr/bin/env python3
"""Tail a Muse session transcript and forward turns to tottie automatically.

Watches session.jsonl for new records, extracts user prompts (started),
assistant conclusions (assistant_message_committed), AND file contents the
agent read (read_file tool results, chunked), scrubs secrets, and POSTs
each as a turn to the core /write endpoint. No per-turn action needed.
Reading IS remembering: nothing is ever pasted manually.

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

def find_latest_session_log() -> str | None:
    base = os.path.expanduser("~/.local/share/muse/sessions")
    if not os.path.exists(base):
        return None
    import glob
    files = glob.glob(f"{base}/**/session.jsonl", recursive=True)
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]

SESSION_ID = os.environ.get(
    "MUSE_SESSION_ID", "latest"
)
default_log = find_latest_session_log() or os.path.expanduser(
    "~/.local/share/muse/sessions/2026/10/26/01a1783d-40f9-7552-8e6f-6cdf013c5a7e/session.jsonl"
)
LOG_PATH = os.environ.get(
    "MUSE_SESSION_LOG",
    default_log
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
# File-read results are chunked so long docs are ingested whole instead
# of truncated: each chunk becomes its own turn, observer decides.
READ_CHUNK = 8000
# call_id -> (tool name, file path) for read_file calls, built live as
# the transcript streams. In-memory only: a restart skips results whose
# calls it never saw, which is exactly the live-read semantic we want.
CALLS: dict[str, tuple[str, str]] = {}


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


def extract(line: str) -> list:
    """Return [(record_id, kind, text)] (possibly empty).

    Besides chat turns this also captures file reads: the agent's
    read_file results flow into memory automatically, chunked. Nothing
    is ever pasted manually — reading IS remembering.
    """
    try:
        rec = json.loads(line)
    except ValueError:
        return []
    payload = rec.get("payload") or {}
    event = payload.get("event") or {}
    kind = event.get("kind")
    if kind == "assistant_tool_calls_committed":
        for call in event.get("tool_calls") or []:
            name = call.get("name") or ""
            if name.split(".")[-1] == "read_file":
                try:
                    args = json.loads(call.get("args") or "{}")
                except ValueError:
                    args = {}
                CALLS[call.get("call_id")] = (
                    name, str(args.get("path") or ""))
        return []
    if kind == "tool_result_batch_committed":
        out = []
        for res in event.get("results") or []:
            info = CALLS.pop(res.get("tool_call_id"), None)
            if not info:
                continue
            _, path = info
            text = (res.get("text") or "").strip()
            if len(text) < MIN_CHARS or text.startswith("Error"):
                continue
            rid = "%s:%s" % (rec.get("id"), res.get("tool_call_id"))
            out.append((rid, "read:" + path, text[:MAX_CHARS * 4]))
        return out
    if kind == "assistant_message_committed":
        text = event.get("text") or ""
        if len(text.strip()) >= MIN_CHARS:
            return [(rec.get("id"), "assistant",
                     text.strip()[:MAX_CHARS])]
    elif kind == "started" and payload.get("kind") == "run":
        prompt = event.get("prompt") or ""
        if len(prompt.strip()) >= MIN_CHARS:
            return [(rec.get("id"), "user", prompt.strip()[:MAX_CHARS])]
    return []


def chunk_read(path: str, text: str) -> list[str]:
    """Split a file read into headed chunks along line boundaries."""
    lines = text.split("\n")
    chunks, cur, size = [], [], 0
    for ln in lines:
        cur.append(ln)
        size += len(ln) + 1
        if size >= READ_CHUNK:
            chunks.append("\n".join(cur))
            cur, size = [], 0
    if cur:
        chunks.append("\n".join(cur))
    total = len(chunks)
    return [f"[file read: {path} — part {i + 1}/{total}]\n{c}"
            for i, c in enumerate(chunks)]


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
    # Explicit (start, end) per line: the offset advances only past turns
    # that forwarded OK. A failed turn keeps its start offset and retries
    # next poll (a 500 used to eat the turn forever).
    fh.seek(state.get("offset", 0))
    pending: list[tuple[int, int, str, str, str]] = []
    end = state.get("offset", 0)
    while True:
        pos = fh.tell()
        line = fh.readline()
        if not line:
            break
        end = fh.tell()
        for item in extract(line):
            if item[0] not in state.get("seen", []):
                pending.append((pos, end, item[0], item[1], item[2]))
    if backfill >= 0:
        pending = pending[-backfill:] if backfill else []
    # Normal tail mode: backfill < 0 means take everything new.
    sent = 0
    for pos, end_pos, rid, kind, text in pending:
        # Owner's own live session is first-party: prompts, the agent's
        # supervised replies, AND files the agent read all arrive
        # user_direct (provenance stays in origin=session_watch).
        # Quarantine guards untrusted OUTSIDE claims (web/tool), never
        # the owner's own working trace.
        trust = "user_direct"
        if kind.startswith("read:"):
            texts = chunk_read(kind[5:], text)
        else:
            texts = [text]
        try:
            for chunk in texts:
                post_turn(scrub(chunk), trust, session,
                          state.get("turn", 0))
                state["turn"] = state.get("turn", 0) + 1
        except Exception as exc:  # noqa: BLE001 - daemon must not die
            print("forward failed: %s" % exc, flush=True)
            state["offset"] = pos  # retry this turn next poll
            break
        state.setdefault("seen", []).append(rid)
        state["offset"] = end_pos
        sent += 1
        print("forwarded %s turn=%d chars=%d parts=%d"
              % (kind[:60], state["turn"], len(text), len(texts)),
              flush=True)
    else:
        state["offset"] = end  # nothing pending: consume the gap
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

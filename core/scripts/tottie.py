#!/usr/bin/env python
"""tottie CLI: the agent's hands. Stdlib only.

  ./venv/bin/python scripts/tottie.py brief --owner frans --session s1 [--text "..."] [--since 0]
  ./venv/bin/python scripts/tottie.py remember --owner frans --session s1 --turn 0 [--trust tool] "text to keep"
  ./venv/bin/python scripts/tottie.py recall --owner frans --session s1 --text "question?" [--k 8]
  ./venv/bin/python scripts/tottie.py sleep --owner frans --session s1
  ./venv/bin/python scripts/tottie.py run --owner frans --session s2 "task needing memory"

Reads TOTTIE_CORE_URL / TOTTIE_API_TOKEN from env (or Tottie/.env).
(cwd=core.)
"""
import argparse
import json
import os
import re
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


def _split_queries(task: str) -> list:
    """Split a multi-part task into recall queries. One embedding over
    4 sub-questions dilutes to the dominant part (Tier-2 drill: NUST
    crowded out Kinsing + Qwen + bridge). Numbered parts split;
    single tasks pass through whole."""
    parts = [p.strip() for p in re.split(r"\(\d+\)\s*", task) if p.strip()]
    parts = [p for p in parts if len(p) > 15]
    if len(parts) < 2:
        alt = [p.strip() for p in re.split(r"\?\s*", task) if p.strip()]
        alt = [p for p in alt if len(p) > 15]
        parts = alt if len(alt) >= 2 else [task]
    return parts


def _interleave(per_part: list, cap: int) -> list:
    """Round-robin merge: concatenate-then-cut drops the LAST part
    entirely (Tier-2 drill: Q4's bridge hits cut off at 18). Dedupes
    by id/summary, keeps rank order within each part."""
    hits: list = []
    seen: set = set()
    longest = max((len(p) for p in per_part), default=0)
    for i in range(longest):
        for p in per_part:
            if i < len(p):
                key = p[i].get("id") or p[i].get("summary")
                if key not in seen:
                    seen.add(key)
                    hits.append(p[i])
                    if len(hits) >= cap:
                        return hits
    return hits


def _injection(briefing: str, hits: list, task: str,
               brief_lines: int = 25) -> str:
    """Build the injected prompt: memory context first, task second.
    Pure (unit-tested); the `run` command only fetches the two parts.
    The brief is capped: a fresh session's first brief floods every
    row since forever (40KB in the Tier-2 drill) and would drown the
    task. Recall hits are the targeted part and stay whole."""
    blines = [ln for ln in briefing.strip().split("\n") if ln.strip()]
    if len(blines) > brief_lines:
        blines = (blines[:brief_lines]
                  + [f"... ({len(blines) - brief_lines} more)"])
    lines = ["# memory context (auto-injected by tottie — use it, do not "
             "ask the user for what is answered here)"]
    lines.append("## brief")
    lines.append("\n".join(blines) if blines else "(no ambient context)")
    lines.append("## recall for this task")
    if hits:
        for h in hits:
            tags = " ".join(f"#{t}" for t in (h.get("tags") or []))
            lines.append(f"- [{h.get('tier')}/{h.get('kind')}] "
                         f"{h.get('summary') or h.get('content') or ''} "
                         f"{tags} ({h.get('why', '')})".rstrip())
    else:
        lines.append("(nothing recalled)")
    lines += ["---", "# task", task]
    return "\n".join(lines) + "\n"


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
    rn = sub.add_parser("run", help="brief + recall a task into one injected prompt")
    rn.add_argument("--owner", default="owner_local")
    rn.add_argument("--session", required=True)
    rn.add_argument("--k", type=int, default=8)
    rn.add_argument("--brief-lines", type=int, default=25)
    rn.add_argument("task")
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
    elif args.cmd == "run":
        code, bout = _req("POST", "/briefing", {
            "owner": args.owner, "session_id": args.session,
        })
        if code != 200:
            _fail(f"/briefing -> {code} {bout}")
        per_part: list = []
        for q in _split_queries(args.task):
            code, rout = _req("POST", "/recall", {
                "query": q, "session_id": args.session,
                "owner": args.owner, "k": args.k,
            })
            if code != 200:
                _fail(f"/recall -> {code} {rout}")
            per_part.append(rout.get("hits") or [])
        # No silent drops: keep every part's hits (prompt budget is
        # the per-part --k dial, not a global cut).
        hits = _interleave(per_part, max(1, len(per_part)) * args.k)
        sys.stdout.write(_injection(
            bout.get("briefing") or "", hits, args.task,
            brief_lines=args.brief_lines))
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

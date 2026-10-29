"""Manager's phase harness for the proactive-memory experiment.

Each phase worker is a FRESH agent that never saw earlier phases and is
never told memory exists. Its whole world is PROMPT.md = unasked briefing
+ task text. Phase texts deliberately omit earlier facts (names, paths,
decisions): if the worker continues correctly, the brain delivered.

Usage (manager runs these between worker spawns):
  phase.py brief <n>     # fetch brief, assemble worker-comet/PROMPT.md
  phase.py remember      # store worker-comet/OUTCOME.md for future briefs
  phase.py intend        # register a due-NOW intention (phase-3 test)
Cursor lives in worker-loop/.cursor. Token comes from the environment
(TOTTIE_API_TOKEN) and is never printed.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent
LOOP = ROOT
BUILD = ROOT.parent / "worker-comet"
CORE = ROOT.parent / "core"
SESSION = "comet-mission"
OWNER = "owner_local"
CURSOR_FILE = LOOP / ".cursor"


def _env():
    tok = os.environ.get("TOTTIE_API_TOKEN", "")
    if not tok:
        raise SystemExit("phase.py: TOTTIE_API_TOKEN not in environment")
    return {
        **os.environ,
        "TOTTIE_API_TOKEN": tok,
        "TOTTIE_OWNER": OWNER,
        "TOTTIE_DB_URL": os.environ.get(
            "TOTTIE_DB_URL", "postgresql://fransnekongo/tottie?host=/tmp"),
        "EMBEDDING_CACHE_DIR": os.environ.get(
            "EMBEDDING_CACHE_DIR",
            str(ROOT.parent.parent / "local LLMS")),
        "PYTHONPATH": str(CORE),
    }


def _text(out) -> str:
    return out.content[0].text


async def _run(coro_fn):
    params = StdioServerParameters(
        command=sys.executable, args=["server.py"], cwd=str(CORE), env=_env())
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            return await coro_fn(s)


def _cursor() -> int:
    try:
        return int(CURSOR_FILE.read_text().strip() or 0)
    except (FileNotFoundError, ValueError):
        return 0


def cmd_brief(phase: str):
    task = (LOOP / f"phases/phase{phase}.md").read_text()
    since = _cursor()

    async def go(s):
        out = await s.call_tool("memory.brief", {
            "session_id": SESSION, "since_event_id": since})
        return json.loads(_text(out))

    body = asyncio.run(_run(go))
    (CURSOR_FILE).write_text(str(body["event_id"]))
    BUILD.mkdir(parents=True, exist_ok=True)
    prompt = (
        f"## phase {phase}\n\n"
        "--- context assembled automatically "
        "(you did not ask for this; use what helps, ignore the rest) ---\n"
        f"{body['briefing']}\n"
        "--- your task ---\n"
        f"{task}\n"
    )
    (BUILD / "PROMPT.md").write_text(prompt)
    print(f"phase {phase}: brief event {body['event_id']} "
          f"(abstain={body['abstain']}, "
          f"new_items={len(body['new_items'])}, "
          f"fired={len(body['fired_intentions'])}) -> PROMPT.md")


def cmd_remember():
    outcome = (BUILD / "OUTCOME.md").read_text()

    async def go(s):
        out = await s.call_tool("memory.remember", {
            "text": outcome[:2000], "session_id": SESSION})
        return json.loads(_text(out))

    body = asyncio.run(_run(go))
    print(f"remembered: {body.get('action')} | {body.get('verdict')}")


def cmd_intend():
    now = datetime.now(timezone.utc).isoformat()

    async def go(s):
        out = await s.call_tool("memory.intend", {
            "content": "Run the FULL pytest suite before declaring the "
                       "mission done.",
            "time_cue": now})
        return json.loads(_text(out))

    body = asyncio.run(_run(go))
    print(f"intention due now: {body}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("brief", "remember", "intend"):
        raise SystemExit("usage: phase.py brief <n> | remember | intend")
    if sys.argv[1] == "brief":
        cmd_brief(sys.argv[2])
    elif sys.argv[1] == "remember":
        cmd_remember()
    else:
        cmd_intend()

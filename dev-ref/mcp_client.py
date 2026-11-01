"""Dev REFERENCE session client: MCP stdio to `python server.py` (cwd=core).

Usage:
  python mcp_client.py brief [text] [session_id] [since_event_id]
  python mcp_client.py remember <text> [session_id]
  python mcp_client.py recall <query> [session_id]
  python mcp_client.py probe-tag <tag>
  python mcp_client.py probe-id <id>
  python mcp_client.py register <agent_id> <label> [session_id]
  python mcp_client.py heartbeat <agent_id>

Defaults: session dev-ref-1. Env forced per task spec:
  TOTTIE_API_TOKEN=changeme-local-token, TOTTIE_OWNER=owner_local.
"""
import asyncio
import json
import os
import sys

CORE_DIR = "/Users/fransnekongo/MEGA/SOFTWARE/NKNGO/NKNGO-Local/portals/tottie/core"
VENV_PY = os.path.join(CORE_DIR, "venv", "bin", "python")
DEFAULT_SESSION = "dev-ref-1"


async def _call(tool: str, args: dict) -> str:
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp import ClientSession

    env = {
        "TOTTIE_API_TOKEN": "changeme-local-token",
        "TOTTIE_OWNER": "owner_local",
        **os.environ,
        "PYTHONPATH": CORE_DIR,
    }
    params = StdioServerParameters(
        command=VENV_PY, args=["server.py"], cwd=CORE_DIR, env=env
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool(tool, args)
            parts = []
            for c in res.content:
                t = getattr(c, "text", None)
                parts.append(t if t is not None else str(c))
            return "\n".join(parts)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in (
            "brief", "remember", "recall", "probe-tag", "probe-id",
            "register", "heartbeat"):
        print(__doc__.strip())
        return 2
    cmd = argv[1]
    if cmd == "brief":
        text = argv[2] if len(argv) > 2 else None
        sid = argv[3] if len(argv) > 3 else DEFAULT_SESSION
        since = int(argv[4]) if len(argv) > 4 else 0
        args = {"session_id": sid, "since_event_id": since}
        if text:
            args["text"] = text
        out = asyncio.run(_call("memory.brief", args))
    elif cmd == "remember":
        if len(argv) < 3:
            print("remember needs <text>")
            return 2
        sid = argv[3] if len(argv) > 3 else DEFAULT_SESSION
        out = asyncio.run(
            _call("memory.remember", {"text": argv[2], "session_id": sid})
        )
    elif cmd == "recall":
        if len(argv) < 3:
            print("recall needs <query>")
            return 2
        sid = argv[3] if len(argv) > 3 else DEFAULT_SESSION
        out = asyncio.run(
            _call("memory.recall", {"query": argv[2], "session_id": sid})
        )
    elif cmd == "register":
        if len(argv) < 4:
            print("register needs <agent_id> <label> [session_id]")
            return 2
        args = {"agent_id": argv[2], "label": argv[3]}
        if len(argv) > 4:
            args["session_id"] = argv[4]
        out = asyncio.run(_call("memory.register", args))
    elif cmd == "heartbeat":
        if len(argv) < 3:
            print("heartbeat needs <agent_id>")
            return 2
        out = asyncio.run(
            _call("memory.heartbeat", {"agent_id": argv[2]}))
    elif cmd == "probe-tag":
        if len(argv) < 3:
            print("probe-tag needs <tag>")
            return 2
        out = asyncio.run(_call("memory.probe", {"tag": argv[2]}))
    else:
        if len(argv) < 3:
            print("probe-id needs <id>")
            return 2
        out = asyncio.run(_call("memory.probe", {"id": argv[2]}))
    # No truncation: agents read this output, and the 4000-char cut hid
    # recall hits behind the card (Tier-1 drill blind spot).
    try:
        print(json.dumps(json.loads(out), indent=2))
    except Exception:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

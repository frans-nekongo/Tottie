"""Dev REFERENCE session client: MCP stdio to `python server.py` (cwd=core).

Usage (positional or --flags, never mixed):
  python mcp_client.py brief [text] [session_id] [since_event_id]
  python mcp_client.py remember <text> [session_id]
  python mcp_client.py recall <query> [session_id]
  python mcp_client.py probe-tag <tag>
  python mcp_client.py probe-id <id>
  python mcp_client.py register <agent_id> <label> [session_id]
  python mcp_client.py heartbeat <agent_id>

Flags: --text --query --session/--session_id --since/--since_event_id
  --k --tag --id --agent_id/--agent --label
Unknown flags (e.g. --owner: owner is fixed by TOTTIE_OWNER env) exit 2
instead of silently becoming the query — a positional-only client once
sent the literal string "--owner" as a recall query and its mush was
misread as a retrieval regression.

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


# Canonical tool-arg name per flag. --owner is DELIBERATELY absent:
# owner is fixed by env and a silently-ignored --owner misleads probes.
_FLAGS = {
    "--text": "text", "--query": "query", "--session": "session_id",
    "--session_id": "session_id", "--since": "since_event_id",
    "--since_event_id": "since_event_id", "--k": "k", "--tag": "tag",
    "--id": "id", "--agent_id": "agent_id", "--agent": "agent_id",
    "--label": "label",
}
_INTS = {"since_event_id", "k"}
_REQUIRED = {
    "remember": ("text",), "recall": ("query",),
    "register": ("agent_id", "label"), "heartbeat": ("agent_id",),
    "probe-tag": ("tag",), "probe-id": ("id"),
}


def parse_cli(argv: list[str]) -> tuple[str, dict]:
    """argv -> (tool, args). Positional (legacy) or --flags, never
    mixed. Raises ValueError with a usage error (caller exits 2)."""
    cmds = ("brief", "remember", "recall", "probe-tag", "probe-id",
            "register", "heartbeat")
    if len(argv) < 2 or argv[1] not in cmds:
        raise ValueError("usage")
    cmd, rest = argv[1], argv[2:]
    if any(t.startswith("-") for t in rest):
        args: dict = {}
        i = 0
        while i < len(rest):
            flag = rest[i]
            if not flag.startswith("-"):
                raise ValueError("positional and --flags must not mix")
            if flag not in _FLAGS:
                raise ValueError(f"unknown flag {flag}")
            if i + 1 >= len(rest) or rest[i + 1].startswith("-"):
                raise ValueError(f"flag {flag} needs a value")
            name = _FLAGS[flag]
            val: object = rest[i + 1]
            if name in _INTS:
                try:
                    val = int(val)
                except ValueError:
                    raise ValueError(f"flag {flag} needs an integer")
            args[name] = val
            i += 2
        if cmd in ("brief", "remember", "recall", "register"):
            args.setdefault("session_id", DEFAULT_SESSION)
        if cmd == "brief":
            args.setdefault("since_event_id", 0)
        for need in _REQUIRED.get(cmd, ()):
            if need not in args:
                raise ValueError(f"{cmd} needs --{need}")
        return cmd, args
    pos = list(rest)
    if cmd == "brief":
        args = {"session_id": pos[1] if len(pos) > 1 else DEFAULT_SESSION,
                "since_event_id": int(pos[2]) if len(pos) > 2 else 0}
        if pos[:1]:
            args["text"] = pos[0]
        return cmd, args
    if cmd == "remember":
        if not pos:
            raise ValueError("remember needs <text>")
        return cmd, {"text": pos[0],
                     "session_id": pos[1] if len(pos) > 1 else DEFAULT_SESSION}
    if cmd == "recall":
        if not pos:
            raise ValueError("recall needs <query>")
        return cmd, {"query": pos[0],
                     "session_id": pos[1] if len(pos) > 1 else DEFAULT_SESSION}
    if cmd == "register":
        if len(pos) < 2:
            raise ValueError("register needs <agent_id> <label> [session_id]")
        args = {"agent_id": pos[0], "label": pos[1]}
        if len(pos) > 2:
            args["session_id"] = pos[2]
        return cmd, args
    if cmd == "heartbeat":
        if not pos:
            raise ValueError("heartbeat needs <agent_id>")
        return cmd, {"agent_id": pos[0]}
    if cmd == "probe-tag":
        if not pos:
            raise ValueError("probe-tag needs <tag>")
        return cmd, {"tag": pos[0]}
    if not pos:
        raise ValueError("probe-id needs <id>")
    return cmd, {"id": pos[0]}


_TOOLS = {
    "brief": "memory.brief", "remember": "memory.remember",
    "recall": "memory.recall", "probe-tag": "memory.probe",
    "probe-id": "memory.probe", "register": "memory.register",
    "heartbeat": "memory.heartbeat",
}


def main(argv: list[str]) -> int:
    try:
        cmd, args = parse_cli(argv)
    except ValueError as e:
        print(__doc__.strip() if str(e) == "usage" else str(e))
        return 2
    out = asyncio.run(_call(_TOOLS[cmd], args))
    # No truncation: agents read this output, and the 4000-char cut hid
    # recall hits behind the card (Tier-1 drill blind spot).
    try:
        print(json.dumps(json.loads(out), indent=2))
    except Exception:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

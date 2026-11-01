"""MCP over real stdio: subprocess server, list/call/read end to end.

One server per module (embedder boot is slow); tables truncated per test.
No LLM: memory.write is explicit, memory.remember uses the heuristic path.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from contextlib import asynccontextmanager

from tests.conftest import PGHOST, PGUSER, TEST_TOKEN

CORE_DIR = Path(__file__).resolve().parent.parent
TEST_DB_URL = f"postgresql://{PGUSER}/tottie_test?host={PGHOST}"

TOOLS = ["memory.brief", "memory.confirm", "memory.forget", "memory.identity",
         "memory.intend", "memory.probe", "memory.recall", "memory.remember",
         "memory.sleep", "memory.write"]


def _env():
    return {
        **os.environ,
        "TOTTIE_API_TOKEN": TEST_TOKEN,
        "TOTTIE_DB_URL": TEST_DB_URL,
        "EMBEDDING_CACHE_DIR": str(CORE_DIR.parent.parent / "local LLMS"),
        "PYTHONPATH": str(CORE_DIR),
    }


# Plain helper, NOT a fixture: pytest-asyncio runs fixture setup and teardown
# in different tasks, and anyio's stdio cancel scope refuses cross-task exit
# ("Attempted to exit cancel scope in a different task"). Inside the test body,
# enter and exit share the test's task. One server boot per test (~15s).
@asynccontextmanager
async def _session():
    params = StdioServerParameters(
        command=sys.executable, args=["server.py"], cwd=str(CORE_DIR), env=_env())
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            yield s


def _text(out) -> str:
    return out.content[0].text


def test_list_tools_cli():
    proc = subprocess.run(
        [sys.executable, "server.py", "--list-tools"], cwd=CORE_DIR,
        env=_env(), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-1000:]
    names = sorted(
        line.split(":")[0] for line in proc.stdout.splitlines() if line.strip()
    )
    assert names == TOOLS


def test_server_instructions_nudge_brief_first():
    # Tier-1 drill: a fresh agent never found memory on its own. The
    # server instructions (delivered on MCP connect) carry the
    # brief-first protocol; the handshake transport is FastMCP's job.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "tottie_mcp_server", CORE_DIR / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = mod.SERVER_INSTRUCTIONS.lower()
    assert "memory.brief" in text and "memory.recall" in text
    assert "never guess" in text


@pytest.mark.asyncio
async def test_list_matches_spec(_test_db):
    async with _session() as mcp:
        tools = await mcp.list_tools()
        assert sorted(t.name for t in tools.tools) == TOOLS
        res = await mcp.list_resources()
        assert [str(r.uri) for r in res.resources] == ["memory://identity"]
        tpl = await mcp.list_resource_templates()
        assert [t.uriTemplate for t in tpl.resourceTemplates] == ["memory://tag/{tag}"]
        prm = await mcp.list_prompts()
        assert [p.name for p in prm.prompts] == ["tottie_context_card"]


@pytest.mark.asyncio
async def test_write_recall_roundtrip(db):
    async with _session() as mcp:
        out = await mcp.call_tool("memory.write", {
            "tier": "knowledge", "content": "MCP roundtrip fact about quokkas.",
            "tags": ["mcp"], "subject": "quokka", "predicate": "mood",
            "object": "cheerful",
        })
        assert json.loads(_text(out))["action"].startswith("NEW")
        out = await mcp.call_tool("memory.recall", {"query": "quokka mood", "k": 3})
        body = json.loads(_text(out))
        assert body["abstain"] is False
        assert "quokka" in body["hits"][0]["summary"].lower()


@pytest.mark.asyncio
async def test_brief_carries_card_new_items_and_cursor(db):
    async with _session() as mcp:
        await mcp.call_tool("memory.write", {
            "tier": "knowledge", "content": "MCP brief fact about wombats.",
            "tags": ["mcp"], "subject": "wombat", "predicate": "mood",
            "object": "sleepy",
        })
        out = await mcp.call_tool("memory.brief", {
            "text": "wombat", "session_id": "mcpbrief", "since_event_id": 0})
        body = json.loads(_text(out))
        assert "wombat" in body["briefing"].lower()
        assert body["abstain"] is False
        assert body["event_id"] > 0
        assert any("wombat" in (i["summary"] or "").lower()
                   for i in body["new_items"])
        out = await mcp.call_tool("memory.brief", {
            "text": "wombat", "session_id": "mcpbrief",
            "since_event_id": body["event_id"]})
        assert json.loads(_text(out))["new_items"] == []
        out = await mcp.call_tool("memory.brief", {"session_id": "mcpbrief"})
        ambient = json.loads(_text(out))
        assert "new since last briefing" in ambient["briefing"]
        assert "wombat" in ambient["briefing"].lower()


@pytest.mark.asyncio
async def test_remember_chitchat_skips_without_llm(db):
    async with _session() as mcp:
        out = await mcp.call_tool("memory.remember", {"text": "thanks!"})
        body = json.loads(_text(out))
        assert body["action"].startswith("SKIP")
    n = await db.fetchval("SELECT count(*) FROM memories")
    assert n == 0


@pytest.mark.asyncio
async def test_probe_identity_intend(db):
    async with _session() as mcp:
        await mcp.call_tool("memory.write", {
            "tier": "identity", "content": "MCP user is Quinn.",
            "tags": ["user"], "subject": "user", "predicate": "name",
            "object": "Quinn",
        })
        out = await mcp.call_tool("memory.identity", {})
        assert "Quinn" in json.loads(_text(out))["identity"][0]["content"]
        out = await mcp.call_tool("memory.probe", {"tag": "user"})
        assert "Quinn" in json.loads(_text(out))["memories"][0]["content"]
        mid = json.loads(_text(out))["memories"][0]["id"]
        out = await mcp.call_tool("memory.probe", {"id": mid})
        assert "Quinn" in json.loads(_text(out))["content"]
        out = await mcp.call_tool("memory.intend", {
            "content": "stretch", "event_cue": "stand up"})
        assert json.loads(_text(out))["content"] == "stretch"


@pytest.mark.asyncio
async def test_confirm_forget_sleep(db):
    async with _session() as mcp:
        await mcp.call_tool("memory.write", {
            "tier": "knowledge", "content": "Web rumor about pigeons.",
            "tags": ["web"], "subject": "pigeon", "predicate": "motive",
            "object": "crumbs",
        })
        row = await db.fetchrow("SELECT id FROM memories")
        mid = str(row["id"])
        out = await mcp.call_tool("memory.forget", {"id": mid})
        assert json.loads(_text(out))["forgot_ids"] == [mid]
        assert await db.fetchrow(
            "SELECT 1 FROM memories WHERE id = %s::uuid", (mid,)) is None
        out = await mcp.call_tool("memory.sleep", {})
        slept = json.loads(_text(out))
        assert slept["available"] is True  # W5: real Consolidator
        assert slept["episodes_replayed"] == 0  # store was forgotten above
        assert slept["semantic_written"] == 0
        assert slept["semantic_error"] is None


@pytest.mark.asyncio
async def test_resources_and_prompt(db):
    async with _session() as mcp:
        await mcp.call_tool("memory.write", {
            "tier": "knowledge", "content": "Room content here.",
            "tags": ["room9"], "subject": "room", "predicate": "note",
            "object": "nine",
        })
        out = await mcp.read_resource("memory://tag/room9")
        assert "Room content here." in out.contents[0].text
        out = await mcp.get_prompt("tottie_context_card", {})
        assert "abstain" in out.messages[0].content.text


def test_no_token_no_start():
    env = {k: v for k, v in _env().items() if k != "TOTTIE_API_TOKEN"}
    proc = subprocess.run(
        [sys.executable, "server.py"], cwd=str(CORE_DIR), env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 1
    assert "TOTTIE_API_TOKEN" in proc.stderr

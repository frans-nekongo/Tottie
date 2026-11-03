"""Agent registry routes: register/heartbeat/list/pair/unpair over ASGI."""
import pytest
import pytest_asyncio

from tests.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest_asyncio.fixture
async def clean_agents(db):
    await db.execute("DELETE FROM agents WHERE id LIKE 'ag-%%'")
    yield
    await db.execute("DELETE FROM agents WHERE id LIKE 'ag-%%'")


@pytest.mark.asyncio
async def test_register_pair_unpair_cycle(client, clean_agents):
    r = await client.post("/agents/register", json={
        "owner": "agown", "id": "ag-pair", "label": "writer",
        "transport": "mcp", "session_id": "s1"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"id": "ag-pair", "connected": False}
    r = await client.post("/agents/pair",
                          json={"owner": "agown", "id": "ag-pair"},
                          headers=AUTH)
    assert r.json() == {"id": "ag-pair", "connected": True}
    r = await client.post("/agents/unpair",
                          json={"owner": "agown", "id": "ag-pair"},
                          headers=AUTH)
    assert r.json() == {"id": "ag-pair", "connected": False}
    r = await client.post("/agents/pair",
                          json={"owner": "agown", "id": "ag-nope"},
                          headers=AUTH)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_heartbeat_registers_and_list_shows_online(client,
                                                         clean_agents, db):
    r = await client.post("/agents/heartbeat",
                          json={"owner": "agown", "id": "ag-heart"},
                          headers=AUTH)
    assert r.json() == {"id": "ag-heart", "connected": False}
    await db.execute(
        "INSERT INTO agents (id, owner, label, last_seen) VALUES "
        "('ag-off', 'agown', 'stale', now() - make_interval(mins => 30))")
    r = await client.get("/agents?owner=agown", headers=AUTH)
    got = {a["id"]: a for a in r.json()["agents"]}
    assert got["ag-heart"]["online"] is True
    assert got["ag-heart"]["label"] == "ag-heart"
    assert got["ag-off"]["online"] is False
    assert got["ag-off"]["connected"] is False


@pytest.mark.asyncio
async def test_unpaired_read_refused_but_visible(client, clean_agents):
    """Bluetooth: registered but never accepted — reads refuse, the row
    still shows (visible + online) so the owner can pair it."""
    r = await client.post("/agents/register", json={
        "owner": "agown", "id": "ag-vis", "label": "watcher"}, headers=AUTH)
    assert r.status_code == 200
    body = {"query": "anything?", "session_id": "s", "owner": "agown",
            "agent_id": "ag-vis"}
    r = await client.post("/recall", json=body, headers=AUTH)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_paired"
    r = await client.get("/probe?tag=x&owner=agown&agent_id=ag-vis",
                         headers=AUTH)
    assert r.status_code == 403
    r = await client.post("/chat", json={
        "text": "hi", "session_id": "s", "owner": "agown",
        "memory": True, "agent_id": "ag-vis"}, headers=AUTH)
    assert r.status_code == 403
    r = await client.post("/chat", json={
        "text": "hi", "session_id": "s", "owner": "agown",
        "memory": True}, headers=AUTH)
    assert r.status_code == 422  # memory reads name their agent
    r = await client.get("/agents?owner=agown", headers=AUTH)
    got = {a["id"]: a for a in r.json()["agents"]}
    assert got["ag-vis"]["connected"] is False
    assert got["ag-vis"]["online"] is True  # refused, but SEEN


@pytest.mark.asyncio
async def test_unknown_read_auto_registers_visible(client, clean_agents, db):
    """A stranger's read is refused AND leaves a visible row — the owner
    sees who knocked in the Agents tab."""
    r = await client.post("/briefing", json={
        "session_id": "s", "owner": "agown", "agent_id": "ag-ghost"},
        headers=AUTH)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_paired"
    row = await db.fetchrow(
        "SELECT connected FROM agents WHERE id = 'ag-ghost'")
    assert row is not None and row["connected"] is False


@pytest.mark.asyncio
async def test_paired_read_served_unpair_refuses(client, clean_agents):
    """Owner accepts -> reads serve; owner revokes -> reads refuse."""
    await client.post("/agents/register", json={
        "owner": "agown", "id": "ag-ok", "label": "ok"}, headers=AUTH)
    await client.post("/agents/pair", json={"owner": "agown", "id": "ag-ok"},
                      headers=AUTH)
    body = {"query": "anything?", "session_id": "s", "owner": "agown",
            "agent_id": "ag-ok"}
    r = await client.post("/recall", json=body, headers=AUTH)
    assert r.status_code == 200  # empty store abstains, but serves
    assert r.json()["abstain"] is True
    await client.post("/agents/unpair",
                      json={"owner": "agown", "id": "ag-ok"}, headers=AUTH)
    r = await client.post("/recall", json=body, headers=AUTH)
    assert r.status_code == 403

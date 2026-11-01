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

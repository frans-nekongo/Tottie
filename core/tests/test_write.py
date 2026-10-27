"""/write over real HTTP: 202 immediacy, curation lands, idempotent retries,
chitchat skips, 401/422 shapes. Live Meta calls — the slow honest tests."""
import asyncio

import pytest

AUTH = {"Authorization": "Bearer test-token"}


def _payload(**kw):
    base = {
        "text": "My name is W1Test.",
        "session_id": "w1",
        "turn": 0,
        "owner": "w1",
        "source": {"trust": "user_direct"},
    }
    base.update(kw)
    return base


async def _wait_row(db, owner, timeout=90):
    for _ in range(timeout):
        row = await db.fetchrow(
            "SELECT tier, kind, content FROM memories WHERE owner = %s ORDER BY id LIMIT 1",
            (owner,),
        )
        if row:
            return row
        await asyncio.sleep(1)
    return None


@pytest.mark.asyncio
async def test_write_202_and_curates(client, db):
    import time

    t0 = time.time()
    r = await client.post("/write", json=_payload(), headers=AUTH)
    dt = time.time() - t0
    assert r.status_code == 202
    assert r.json()["mode"] == "queued"
    assert r.json()["event_id"]
    assert dt < 5.0, f"route blocked {dt:.1f}s (must not wait for the model)"
    row = await _wait_row(db, "w1")
    assert row is not None, "worker never persisted the turn"
    assert "W1Test" in row["content"]
    assert row["tier"] == "identity"
    ev = await db.fetchrow(
        "SELECT scribe_action FROM memory_events WHERE session_id = 'w1'"
    )
    assert ev["scribe_action"]["op"] == "NEW"


@pytest.mark.asyncio
async def test_write_idempotent(client, db):
    p = _payload(session_id="w1dup", owner="w1dup", turn=3)
    assert (await client.post("/write", json=p, headers=AUTH)).status_code == 202
    assert (await client.post("/write", json=p, headers=AUTH)).status_code == 202
    for _ in range(90):
        n = await db.fetchval(
            "SELECT count(*) FROM memories WHERE owner = 'w1dup'"
        )
        if n >= 1:
            break
        await asyncio.sleep(1)
    await asyncio.sleep(3)  # let the duplicate finish racing
    n = await db.fetchval("SELECT count(*) FROM memories WHERE owner = 'w1dup'")
    assert n == 1, f"double POST wrote {n} rows"


@pytest.mark.asyncio
async def test_write_chitchat_skips_fast(client, db):
    r = await client.post(
        "/write", json=_payload(session_id="w1chat", owner="w1chat", text="thanks!"),
        headers=AUTH,
    )
    assert r.status_code == 202
    for _ in range(30):
        ev = await db.fetchrow(
            "SELECT scribe_action FROM memory_events WHERE session_id = 'w1chat'"
        )
        if ev:
            break
        await asyncio.sleep(1)
    assert ev is not None
    assert ev["scribe_action"]["op"] == "SKIP"
    n = await db.fetchval("SELECT count(*) FROM memories WHERE owner = 'w1chat'")
    assert n == 0


@pytest.mark.asyncio
async def test_write_auth_and_shapes(client):
    p = _payload()
    assert (await client.post("/write", json=p)).status_code == 401
    bad = {"Authorization": "Bearer wrong"}
    assert (await client.post("/write", json=p, headers=bad)).status_code == 401
    q = _payload(text="   ")
    assert (await client.post("/write", json=q, headers=AUTH)).status_code == 422
    q = _payload()
    q["source"] = {"trust": "evil"}
    assert (await client.post("/write", json=q, headers=AUTH)).status_code == 422

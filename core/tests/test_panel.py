"""Panel endpoints: /graph shape, /memories filters, /chat ablation.

The ablation test is deterministic: a random token (Zxqpl-77) seeded in the
store is unguessable, so memory=true answers it and memory=false cannot.
Live Meta for chat replies only.
"""
import asyncio

import pytest

from app.config import Settings
from app.embeddings import Embedder
from tests.conftest import TEST_TOKEN
from tests.test_recall import seed  # noqa: F401 (shared seed helper)

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
OWNER = "r4"


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


SEEDS = [
    {"name": "vault", "kind": "fact",
     "content": "The treehouse password is Zxqpl-77.", "tags": ["vault"]},
    {"name": "name", "tier": "identity", "kind": "identity",
     "content": "The user's name is Panel.", "tags": ["user"]},
]


@pytest.mark.asyncio
async def test_graph_shape_and_tier_filter(client, db, emb):
    ids = await seed(db, emb, OWNER, SEEDS)
    await db.execute(
        "INSERT INTO memory_links (owner, src, dst, relation) VALUES (%s,%s,%s,'tag')",
        (OWNER, ids["vault"], ids["name"]),
    )
    r = await client.get(f"/graph?owner={OWNER}", headers=AUTH)
    assert r.status_code == 200
    out = r.json()
    assert len(out["nodes"]) == 2
    assert out["nodes"][0]["label"]
    assert len(out["links"]) == 1
    assert out["links"][0]["source"] == ids["vault"]
    assert all("ranked_out" in n and "quarantined" in n for n in out["nodes"])
    await db.execute(
        "UPDATE memories SET ranked_out = true WHERE id = %s::uuid",
        (ids["vault"],),
    )
    r = await client.get(f"/graph?owner={OWNER}", headers=AUTH)
    by_id = {n["id"]: n for n in r.json()["nodes"]}
    assert by_id[ids["vault"]]["ranked_out"] is True  # still shown, greyed
    assert by_id[ids["name"]]["ranked_out"] is False
    r = await client.get(f"/graph?owner={OWNER}&tiers=identity", headers=AUTH)
    assert {n["tier"] for n in r.json()["nodes"]} == {"identity"}
    r = await client.get("/graph?owner=x&tiers=bogus", headers=AUTH)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_memories_filters_and_lookup(client, db, emb):
    ids = await seed(db, emb, OWNER, SEEDS)
    r = await client.get(f"/memories?owner={OWNER}", headers=AUTH)
    assert len(r.json()["memories"]) == 2
    r = await client.get(
        f"/memories?owner={OWNER}&quarantined=true", headers=AUTH)
    assert r.json()["memories"] == []
    r = await client.get(
        f"/memories?owner={OWNER}&id={ids['vault']}", headers=AUTH)
    assert "Zxqpl" in r.json()["memories"][0]["content"]
    r = await client.get(
        f"/memories?owner={OWNER}&id=00000000-0000-0000-0000-000000000000",
        headers=AUTH)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_chat_ablation_on_vs_off(client, db, emb):
    await seed(db, emb, OWNER, SEEDS)
    on = await client.post("/chat", json={
        "text": "What is the treehouse password?", "session_id": "abl",
        "owner": OWNER, "memory": True,
    }, headers=AUTH)
    assert on.status_code == 200
    body = on.json()
    assert "Zxqpl" in body["reply"], body
    assert body["abstain"] is False
    assert body["path"], "no firing path for the graph"
    off = await client.post("/chat", json={
        "text": "What is the treehouse password?", "session_id": "abl",
        "owner": OWNER, "memory": False,
    }, headers=AUTH)
    assert "Zxqpl" not in off.json()["reply"], off.json()
    assert off.json()["card"] is None
    assert off.json()["event_id"] is None
    for _ in range(60):  # ON arm enqueued its turn; OFF wrote nothing
        n = await db.fetchval(
            "SELECT count(*) FROM memory_events WHERE session_id = 'abl' "
            "AND cue IS NULL AND utterance LIKE %s", ("What is the treehouse%",))
        if n and n >= 1:
            break
        await asyncio.sleep(2)
    assert n == 1, f"OFF arm wrote, or ON arm lost its turn (n={n})"


@pytest.mark.asyncio
async def test_chat_auth_and_shapes(client):
    body = {"text": "hi", "session_id": "s", "owner": OWNER}
    assert (await client.post("/chat", json=body)).status_code == 401
    q = dict(body, text="   ")
    assert (await client.post("/chat", json=q, headers=AUTH)).status_code == 422

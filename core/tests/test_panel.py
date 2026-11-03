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
async def test_graph_includes_fresh_low_salience(client, db, emb, monkeypatch):
    """The brain shows births, not just celebrities: a newest row with
    bottom salience must appear even when the salient cap is full."""
    import app.routes.graph as graph_mod

    monkeypatch.setattr(graph_mod, "GRAPH_SALIENT", 2)
    monkeypatch.setattr(graph_mod, "GRAPH_FRESH", 1)
    ids = await seed(db, emb, "r4fresh", [
        {"name": "old1", "content": "Old salient fact one.", "salience": 0.9},
        {"name": "old2", "content": "Old salient fact two.", "salience": 0.9},
        {"name": "old3", "content": "Old salient fact three.", "salience": 0.9},
        {"name": "new", "content": "Fresh fact just landed.", "salience": 0.1},
    ])
    r = await client.get("/graph?owner=r4fresh", headers=AUTH)
    assert r.status_code == 200
    got = {n["id"] for n in r.json()["nodes"]}
    assert ids["new"] in got, got
    assert len(got) == 3


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


@pytest.mark.asyncio
async def test_chat_inline_mode_curates_synchronously(
        _test_db, _clean_tables, monkeypatch, db, emb):
    """INLINE_WRITE=1 starts no workers: /chat must curate inline, exactly
    like /write, or the turn is silently never remembered (the UI amnesia
    regression). The row exists the moment the response returns: no
    polling, no queue. Live Meta for observe + reply."""
    import uuid

    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    from app.config import get_settings
    from app.main import create_app
    from tests.conftest import TEST_CACHE_DIR, TEST_DB_URL

    monkeypatch.setenv("TOTTIE_DB_URL", TEST_DB_URL)
    monkeypatch.setenv("TOTTIE_API_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("EMBEDDING_CACHE_DIR", TEST_CACHE_DIR)
    monkeypatch.setenv("TOTTIE_INLINE_WRITE", "1")
    get_settings.cache_clear()
    ow = f"r4_{uuid.uuid4().hex[:8]}"
    app = create_app()
    async with LifespanManager(app):
        assert app.state.queue.depth == 0
        assert app.state.queue._tasks == []  # no workers in inline mode
        transport = ASGITransport(app=app)
        async with AsyncClient(
                transport=transport, base_url="http://test") as c:
            r = await c.post("/chat", json={
                "text": "My dog is called Rex.", "session_id": "inline1",
                "owner": ow, "memory": True,
            }, headers=AUTH)
            assert r.status_code == 200, r.text
            assert r.json()["event_id"] is not None
    got = await db.fetchval(
        "SELECT content FROM memories WHERE owner = %s", (ow,))
    assert got is not None and "Rex" in got, "turn never curated"
    n = await db.fetchval(
        "SELECT count(*) FROM memory_events WHERE owner = %s "
        "AND session_id = 'inline1' AND turn = 0 "
        "AND scribe_action->>'op' IN "
        "('NEW','UPDATE','SUPERSEDE','SKIP','RAW')", (ow,))
    assert n == 1, "curation event missing"

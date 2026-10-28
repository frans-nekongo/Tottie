"""POST /briefing: ambient surface. Deterministic — recall needs the real
embedder only, no LLM. Seeds go in via SQL."""
import pytest
from psycopg.types.json import Json

from app.config import Settings
from app.embeddings import Embedder
from tests.conftest import TEST_TOKEN
from tests.test_recall import seed  # noqa: F401 (shared seed helper)

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
OWNER = "br"
SEEDS = [
    {"name": "city", "kind": "fact",
     "content": "Frans lives in Windhoek.", "tags": ["home"]},
]


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


@pytest.mark.asyncio
async def test_briefing_explicit_text(client, db, emb):
    await seed(db, emb, OWNER, SEEDS)
    r = await client.post("/briefing", json={
        "session_id": "br1", "owner": OWNER,
        "text": "Where does Frans live?", "since_event_id": 0,
    }, headers=AUTH)
    assert r.status_code == 200
    out = r.json()
    assert "Windhoek" in (out["card"] or "")
    assert "Windhoek" in out["briefing"]
    assert out["abstain"] is False
    assert out["event_id"] >= 0


@pytest.mark.asyncio
async def test_briefing_session_context_no_text(client, db, emb):
    await seed(db, emb, OWNER, SEEDS)
    await db.execute(
        "INSERT INTO memory_events (session_id, turn, utterance) "
        "VALUES (%s, 0, %s)",
        ("brctx", "Where does Frans live?"),
    )
    r = await client.post("/briefing", json={
        "session_id": "brctx", "owner": OWNER,
    }, headers=AUTH)
    assert r.status_code == 200
    assert "Windhoek" in (r.json()["card"] or ""), \
        "no-text briefing must recall on the session's own utterances"


@pytest.mark.asyncio
async def test_briefing_since_cursor(client, db, emb):
    ids = await seed(db, emb, OWNER, SEEDS)
    r = await client.post("/briefing", json={
        "session_id": "brc", "owner": OWNER, "text": "hi",
        "since_event_id": 0,
    }, headers=AUTH)
    cur = r.json()["event_id"]
    await db.execute(
        "INSERT INTO memory_events (session_id, turn, utterance, scribe_action) "
        "VALUES (%s, 1, %s, %s)",
        ("brc", "Frans lives in Windhoek.",
         Json({"op": "NEW", "memory_ids": [ids["city"]]})),
    )
    r2 = await client.post("/briefing", json={
        "session_id": "brc", "owner": OWNER, "text": "hi",
        "since_event_id": cur,
    }, headers=AUTH)
    got = {it["id"] for it in r2.json()["new_items"]}
    assert ids["city"] in got, "cursor must surface formed-since memories"
    assert "new since last briefing" in r2.json()["briefing"]
    r3 = await client.post("/briefing", json={
        "session_id": "brc", "owner": OWNER, "text": "hi",
        "since_event_id": r2.json()["event_id"],
    }, headers=AUTH)
    assert r3.json()["new_items"] == []


@pytest.mark.asyncio
async def test_briefing_empty_abstains(client, db):
    r = await client.post("/briefing", json={
        "session_id": "brempty", "owner": "brempty",
    }, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["abstain"] is True
    assert "nothing relevant" in r.json()["briefing"]

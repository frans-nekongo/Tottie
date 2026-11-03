"""POST /briefing: ambient surface. Deterministic — recall needs the real
embedder only, no LLM. Seeds go in via SQL."""
import pytest
from psycopg.types.json import Json

from app.config import Settings
from app.embeddings import Embedder
from tests.conftest import TEST_TOKEN
from tests.test_recall import pair_owner, seed  # noqa: F401 (shared helpers)

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
        "session_id": "br1", "owner": OWNER, "agent_id": "ag-seed",
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
        "INSERT INTO memory_events (owner, session_id, turn, utterance) "
        "VALUES (%s, %s, 0, %s)",
        (OWNER, "brctx", "Where does Frans live?"),
    )
    r = await client.post("/briefing", json={
        "session_id": "brctx", "owner": OWNER, "agent_id": "ag-seed",
    }, headers=AUTH)
    assert r.status_code == 200
    assert "Windhoek" in (r.json()["card"] or ""), \
        "no-text briefing must recall on the session's own utterances"


@pytest.mark.asyncio
async def test_briefing_since_cursor(client, db, emb):
    ids = await seed(db, emb, OWNER, SEEDS)
    r = await client.post("/briefing", json={
        "session_id": "brc", "owner": OWNER, "agent_id": "ag-seed",
        "text": "hi", "since_event_id": 0,
    }, headers=AUTH)
    cur = r.json()["event_id"]
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance, "
        "scribe_action) VALUES (%s, %s, 1, %s, %s)",
        (OWNER, "brc", "Frans lives in Windhoek.",
         Json({"op": "NEW", "memory_ids": [ids["city"]]})),
    )
    r2 = await client.post("/briefing", json={
        "session_id": "brc", "owner": OWNER, "agent_id": "ag-seed",
        "text": "hi", "since_event_id": cur,
    }, headers=AUTH)
    got = {it["id"] for it in r2.json()["new_items"]}
    assert ids["city"] in got, "cursor must surface formed-since memories"
    assert "new since last briefing" in r2.json()["briefing"]
    r3 = await client.post("/briefing", json={
        "session_id": "brc", "owner": OWNER, "agent_id": "ag-seed",
        "text": "hi", "since_event_id": r2.json()["event_id"],
    }, headers=AUTH)
    assert r3.json()["new_items"] == []


@pytest.mark.asyncio
async def test_briefing_suppresses_identity_on_work_stimulus(client, db, emb):
    """Executive suppression: a work stimulus briefs work context, not the
    pinned identity slice (live: Amara rows polluted a code prompt).
    Steady state (cursor advanced past the news): the identity row appears
    nowhere, the work fact does."""
    import uuid

    ow = f"br_{uuid.uuid4().hex[:8]}"
    await seed(db, emb, ow, [
        {"name": "who", "tier": "identity", "kind": "identity",
         "content": "Owner is Amara Quietstorm.", "tags": ["owner"]},
        {"name": "work", "kind": "fact",
         "content": "Streak counts back from today if done.",
         "tags": ["streak"]},
    ])
    first = await client.post("/briefing", json={
        "session_id": "brw", "owner": ow, "agent_id": "ag-seed",
        "text": "how do streaks count", "since_event_id": 0,
    }, headers=AUTH)
    r = await client.post("/briefing", json={
        "session_id": "brw", "owner": ow, "agent_id": "ag-seed",
        "text": "how do streaks count",
        "since_event_id": first.json()["event_id"],
    }, headers=AUTH)
    assert r.json()["new_items"] == []
    assert "Amara Quietstorm" not in (r.json()["card"] or "")
    assert "Amara Quietstorm" not in r.json()["briefing"]
    assert "Streak counts back" in (r.json()["card"] or "")


@pytest.mark.asyncio
async def test_briefing_includes_identity_on_identity_frame(client, db, emb):
    """Gating, not blindness: an explicit identity frame still pins the
    identity slice into the brief."""
    import uuid

    ow = f"br_{uuid.uuid4().hex[:8]}"
    await seed(db, emb, ow, [
        {"name": "who", "tier": "identity", "kind": "identity",
         "content": "Owner is Amara Quietstorm.", "tags": ["owner"]},
    ])
    r = await client.post("/briefing", json={
        "session_id": "bri", "owner": ow, "agent_id": "ag-seed",
        "text": "tell me who am i", "since_event_id": 0,
    }, headers=AUTH)
    assert "Amara Quietstorm" in (r.json()["card"] or "")


@pytest.mark.asyncio
async def test_briefing_empty_abstains(client, db):
    await pair_owner(db, "brempty")
    r = await client.post("/briefing", json={
        "session_id": "brempty", "owner": "brempty",
        "agent_id": "ag-seed",
    }, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["abstain"] is True
    assert "nothing relevant" in r.json()["briefing"]

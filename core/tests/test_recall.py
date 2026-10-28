"""Recall over seeded rows: real DB, real embedder, no LLM (except the one
live round-trip). Seeds embed their content exactly like the Scribe does."""
import asyncio
import uuid

import pytest
from psycopg.types.json import Json

from app.config import Settings
from app.db import pgvector_literal
from app.embeddings import Embedder
from tests.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
OWNER = "r2"


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


async def seed(db, emb, owner, items):
    """Insert memory rows with real embeddings. Returns {name: id}."""
    ids = {}
    for i, it in enumerate(items):
        vec, _ = await emb.embed(it["content"])
        row = await db.execute_returning(
            "INSERT INTO memories (owner, tier, kind, content, tags, salience, "
            "trust, source, embedding, embedding_model, hash, quarantined, "
            "valid_to) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s,%s,%s) "
            "RETURNING id",
            (
                owner, it.get("tier", "knowledge"), it.get("kind", "fact"),
                it["content"], it.get("tags", []), it.get("salience", 0.7),
                it.get("trust", "user_direct"),
                Json({"session": it.get("session", "seed"), "turn": i}),
                pgvector_literal(vec), emb.model_name, uuid.uuid4().hex,
                it.get("quarantined", False), it.get("valid_to"),
            ),
        )
        ids[it.get("name", f"row{i}")] = str(row["id"])
    return ids


SEEDS = [
    {"name": "name", "tier": "identity", "kind": "identity",
     "content": "The user's name is Recallia.", "tags": ["user"]},
    {"name": "deploy", "kind": "decision",
     "content": "Deploy checklist lives in the runbook under Friday procedures.",
     "tags": ["deploy", "project/A"]},
    {"name": "lake", "tier": "episodic", "kind": "event",
     "content": "Photos from the lake house weekend with old friends.",
     "tags": ["personal"]},
    {"name": "quar", "kind": "decision",
     "content": "Deploy checklist says ship on Fridays without review.",
     "tags": ["deploy"], "trust": "web", "quarantined": True},
    {"name": "old", "kind": "fact",
     "content": "Deploy checklist was kept on a sticky note.",
     "tags": ["deploy"], "valid_to": "2020-01-01"},
]


@pytest.mark.asyncio
async def test_ranked_recall_finds_answer(client, db, emb):
    await seed(db, emb, OWNER, SEEDS)
    r = await client.post("/recall", json={
        "query": "Where is the deploy checklist?", "session_id": "s",
        "owner": OWNER,
    }, headers=AUTH)
    assert r.status_code == 200
    out = r.json()
    assert out["abstain"] is False
    assert out["mode"] == "ranked"
    assert "runbook" in out["hits"][0]["summary"]
    assert out["hits"][0]["why"].startswith("QUESTION -> ")
    assert "Recallia" in out["card"]  # identity header always rides along
    assert out["path"], "story path missing"
    assert out["candidates_matched"] >= 1
    # ledger + rehearsal
    ev = await db.fetchrow(
        "SELECT cue FROM memory_events WHERE utterance LIKE %s",
        ("Where is the deploy%",),
    )
    assert ev["cue"]["type"] == "QUESTION"
    n = await db.fetchval(
        "SELECT access_count FROM memories WHERE content LIKE %s",
        ("%runbook%",),
    )
    assert n >= 1


@pytest.mark.asyncio
async def test_quarantine_superseded_owner_never_leak(client, db, emb):
    other = await seed(db, emb, "intruder", [
        {"name": "x", "content": "Deploy checklist intruder copy.", "tags": ["deploy"]},
    ])
    mine = await seed(db, emb, OWNER, SEEDS)
    r = await client.post("/recall", json={
        "query": "deploy checklist", "session_id": "s", "owner": OWNER, "k": 20,
    }, headers=AUTH)
    got = {h["id"] for h in r.json()["hits"]}
    assert mine["quar"] not in got, "quarantined row injected"
    assert mine["old"] not in got, "superseded row injected"
    assert other["x"] not in got, "cross-owner leak"
    assert mine["deploy"] in got


@pytest.mark.asyncio
async def test_abstain_on_empty_store(client):
    r = await client.post("/recall", json={
        "query": "What is the meaning of life?", "session_id": "s",
        "owner": "nobody",
    }, headers=AUTH)
    out = r.json()
    assert out["abstain"] is True
    assert out["confidence"] == 0.0
    assert out["card"] is None
    assert out["hits"] == []


@pytest.mark.asyncio
async def test_tiers_filter(client, db, emb):
    await seed(db, emb, OWNER, SEEDS)
    r = await client.post("/recall", json={
        "query": "deploy", "session_id": "s", "owner": OWNER, "tiers": ["episodic"],
    }, headers=AUTH)
    assert {h["tier"] for h in r.json()["hits"]} <= {"episodic"}
    r = await client.post("/recall", json={
        "query": "deploy", "session_id": "s", "owner": OWNER, "tiers": ["bogus"],
    }, headers=AUTH)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_command_policy_assembles_kit(client, db, emb):
    await seed(db, emb, OWNER, SEEDS)
    r = await client.post("/recall", json={
        "query": "Show the deploy checklist for #project/A",
        "session_id": "s", "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert out["cue"]["type"] == "COMMAND"
    assert out["cue"]["policy"] == "command"
    assert any(h["kind"] == "decision" for h in out["hits"])


@pytest.mark.asyncio
async def test_bfs_surfaces_associated_row(client, db, emb):
    ids = await seed(db, emb, OWNER, SEEDS)
    await db.execute(
        "INSERT INTO memory_links (owner, src, dst, relation, weight) "
        "VALUES (%s, %s::uuid, %s::uuid, 'tag', 1.0)",
        (OWNER, ids["deploy"], ids["lake"]),
    )
    r = await client.post("/recall", json={
        "query": "deploy checklist runbook Friday procedures",
        "session_id": "s", "owner": OWNER, "k": 8,
    }, headers=AUTH)
    lake = [h for h in r.json()["hits"] if h["id"] == ids["lake"]]
    assert lake, "BFS missed the linked row"


@pytest.mark.asyncio
async def test_prospective_fires_and_registers(client, db, emb):
    await seed(db, emb, OWNER, SEEDS)
    await db.execute(
        "INSERT INTO intentions (owner, content, time_cue) "
        "VALUES (%s, 'past due', now() - interval '1 hour')"
        ", (%s, 'future', now() + interval '1 day')",
        (OWNER, OWNER),
    )
    r = await client.post("/recall", json={
        "query": "remind me to water the plants tomorrow",
        "session_id": "s", "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert [f["content"] for f in out["fired_intentions"]] == ["past due"]
    assert out["registered_intention"]["content"] == "water the plants"
    assert out["registered_intention"]["time_cue"] is not None
    n = await db.fetchval(
        "SELECT count(*) FROM intentions WHERE owner = %s AND status = 'pending'",
        (OWNER,),
    )
    assert n == 2  # future + newly registered


@pytest.mark.asyncio
async def test_replay_branch_orders_session(client, db, emb):
    ids = await seed(db, emb, OWNER, SEEDS)
    for i, (utt, mid) in enumerate([
        ("My name is Recallia", ids["name"]),
        ("Where is the checklist", ids["deploy"]),
    ]):
        await db.execute(
            "INSERT INTO memory_events (owner, session_id, turn, utterance, "
            "observer_verdict, scribe_action) VALUES (%s,%s,%s,%s,%s,%s)",
            (OWNER, "rsess", i, utt, Json({"keep": True}),
             Json({"op": "NEW", "memory_ids": [mid]})),
        )
    await client.post("/recall", json={  # recall events must not pollute replay
        "query": "noise", "session_id": "rsess", "owner": OWNER,
    }, headers=AUTH)
    r = await client.post("/recall", json={
        "query": "where were we?", "session_id": "rsess", "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert out["mode"] == "replay"
    assert out["abstain"] is False
    assert [t["turn"] for t in out["timeline"]] == [0, 1]
    assert all("noise" not in t["utterance"] for t in out["timeline"])


@pytest.mark.asyncio
async def test_replay_follows_turns_not_insert_order(client, db, emb):
    """Concurrency inversion: turn 1 committed before turn 0 — replay must
    still narrate 0 then 1 (logical order, never physical)."""
    ids = await seed(db, emb, OWNER, [
        {"name": "a", "content": "First the owner woke up.",
         "tags": ["morning"]},
        {"name": "b", "content": "Then the owner ran a mile.",
         "tags": ["run"]},
    ])
    for turn, (utt, mid) in [
        (1, ("Then the owner ran a mile.", ids["b"])),
        (0, ("First the owner woke up.", ids["a"])),
    ]:
        await db.execute(
            "INSERT INTO memory_events (owner, session_id, turn, utterance, "
            "observer_verdict, scribe_action) VALUES (%s,%s,%s,%s,%s,%s)",
            (OWNER, "inv", turn, utt, Json({"keep": True}),
             Json({"op": "NEW", "memory_ids": [mid]})),
        )
    r = await client.post("/recall", json={
        "query": "where were we?", "session_id": "inv", "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert out["mode"] == "replay"
    assert [t["turn"] for t in out["timeline"]] == [0, 1]


@pytest.mark.asyncio
async def test_associative_leg_case_insensitive(client, db, emb):
    """#FOOD in the query must fire the tag leg against stored 'food':
    the read path honors the same normalization as the write path."""
    await seed(db, emb, OWNER, [
        {"name": "ramen", "content": "The user adores midnight ramen.",
         "tags": ["food"]},
    ])
    r = await client.post("/recall", json={
        "query": "anything on #FOOD?", "session_id": "ci", "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert out["abstain"] is False
    ramen = [h for h in out["hits"] if "ramen" in h["summary"]]
    assert ramen, out["hits"]
    assert "tag #" in ramen[0]["why"], ramen[0]["why"]


@pytest.mark.asyncio
async def test_probe_case_insensitive(client, db, emb):
    await seed(db, emb, OWNER, [
        {"name": "ramen", "content": "The user adores midnight ramen.",
         "tags": ["food"]},
    ])
    r = await client.get(f"/probe?tag=%23FOOD&owner={OWNER}", headers=AUTH)
    got = {m["content"] for m in r.json()["memories"]}
    assert any("ramen" in c for c in got), got


@pytest.mark.asyncio
async def test_identity_and_probe_endpoints(client, db, emb):
    await seed(db, emb, OWNER, SEEDS)
    r = await client.get(f"/identity?owner={OWNER}", headers=AUTH)
    assert "Recallia" in r.json()["identity"][0]["content"]
    r = await client.get(f"/probe?tag=deploy&owner={OWNER}", headers=AUTH)
    got = {m["content"] for m in r.json()["memories"]}
    assert any("runbook" in c for c in got)
    assert not any("without review" in c for c in got)  # quarantined stays out


def test_card_truncates_at_line_boundary():
    """Dogfood night: the card cut mid-word ('#invoi', 'probe d'). Long
    cards now end at a newline with an honest marker, never mid-token."""
    from app.agents.retrieve import _card

    hits = [{
        "id": str(i), "tier": "knowledge", "kind": "fact",
        "summary": f"padded fact number {i} " + "x" * 120,
        "tags": [f"tag{i}"], "score": 1.0 - i * 0.01,
        "why": "QUESTION -> vector #1",
    } for i in range(30)]
    card = _card([], hits, False)
    assert card is not None and len(card) <= 1600 + 2
    assert card.endswith("\n…"), card[-20:]
    # every body line ends with ")": the cut kept whole lines only
    assert card[:-2].endswith(")"), card[-30:]


@pytest.mark.asyncio
async def test_recall_auth_and_shapes(client):
    body = {"query": "x", "session_id": "s", "owner": OWNER}
    assert (await client.post("/recall", json=body)).status_code == 401
    # Deliberately wrong token, built so no literal secret sits in source.
    bad = {"Authorization": "Bearer " + "x" * 12}
    assert (await client.post("/recall", json=body, headers=bad)).status_code == 401
    q = dict(body, query="   ")
    assert (await client.post("/recall", json=q, headers=AUTH)).status_code == 422


@pytest.mark.asyncio
async def test_recall_latency_smoke(client, db, emb):
    """100-row store answers fast. Bound is anti-regression (CI-safe), not
    the 300ms p95 acceptance — the measured number is what we judge."""
    import time

    vecs = []
    for i in range(5):
        v, _ = await emb.embed(f"Filler memory number {i} about routine topics.")
        vecs.append(v)
    for i in range(100):
        await db.execute(
            "INSERT INTO memories (owner, tier, kind, content, tags, salience, "
            "trust, source, embedding, embedding_model, hash) "
            "VALUES (%s,'knowledge','fact',%s,%s,0.5,'user_direct',%s,"
            "%s::vector,%s,%s)",
            (OWNER, f"Filler memory {i} about routine topic {i % 7}.",
             [f"t{i % 7}"], Json({"session": "perf", "turn": i}),
             pgvector_literal(vecs[i % 5]), emb.model_name, uuid.uuid4().hex),
        )
    t0 = time.monotonic()
    r = await client.post("/recall", json={
        "query": "routine topic 3", "session_id": "s", "owner": OWNER,
    }, headers=AUTH)
    dt = (time.monotonic() - t0) * 1000
    print(f"\nrecall p1 over 100 rows: {dt:.0f}ms")
    assert r.status_code == 200
    assert dt < 2000, f"recall too slow: {dt:.0f}ms"


@pytest.mark.asyncio
async def test_live_write_recall_roundtrip(client, db):
    """The 'it just knows' proof: live Meta write, then recall finds it."""
    r = await client.post("/write", json={
        "text": "My grandmother's soup needs extra thyme and a bay leaf.",
        "session_id": "r2live", "turn": 0, "owner": OWNER,
    }, headers=AUTH)
    assert r.status_code == 202
    for _ in range(120):
        n = await db.fetchval(
            "SELECT count(*) FROM memory_events WHERE session_id = 'r2live'"
        )
        if n and n >= 1:
            break
        await asyncio.sleep(2)
    r = await client.post("/recall", json={
        "query": "What does grandmother's soup need?", "session_id": "r2live",
        "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert out["abstain"] is False, out
    assert "thyme" in " ".join(h["summary"] for h in out["hits"])


@pytest.mark.asyncio
async def test_recall_story_narrates(client, db, emb):
    ids = await seed(db, emb, "rstory", [
        {"name": "lake", "content": "The lake cabin has a red canoe.",
         "tags": ["lake"]},
    ])
    r = await client.post("/recall", json={
        "query": "What is at the lake cabin?", "session_id": "rstory",
        "owner": "rstory",
    }, headers=AUTH)
    out = r.json()
    assert "QUESTION" in out["story"]
    assert "vector" in out["story"] or "lexical" in out["story"]
    assert "confidence" in out["story"]
    r = await client.post("/recall", json={
        "query": "Anything at all?", "session_id": "rstory",
        "owner": "rstory_empty",
    }, headers=AUTH)
    assert "abstained" in r.json()["story"]
    assert len(ids) == 1

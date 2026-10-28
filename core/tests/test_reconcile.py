"""Reconcile: NEW/SKIP/UPDATE/SUPERSEDE matrix over crafted candidates (real DB
+ real embedder, deterministic), live vegetarian chain, concurrency invariant,
poison partition, confirm/forget, tag links, quarantine-safe BFS."""
import asyncio
import uuid

import pytest
from psycopg.types.json import Json

from app.agents.observer import Observation
from app.agents import reconcile, scribe
from app.config import Settings
from app.db import pgvector_literal
from app.embeddings import Embedder
from app.queue import WorkerTurn
from tests.conftest import TEST_TOKEN
from tests.test_recall import seed  # noqa: F401 (shared seed helper)

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
OWNER = "r3"


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


def _obs(cands, salience=0.8, verdict="keep", provider="stub"):
    return Observation(
        keep=True, salience=salience, surprise=0.9, candidates=cands,
        verdict=verdict, provider=provider,
    )


def _cand(content, kind="preference", tier="knowledge", subject=None,
          predicate=None, obj=None, tags=None):
    return {"kind": kind, "tier": tier, "subject": subject,
            "predicate": predicate, "object": obj, "content": content,
            "tags": tags or [], "principle": None}


def _turn(text, trust="user_direct", session="r3", turn=0, owner=OWNER):
    return WorkerTurn(text=text, session_id=session, turn=turn, owner=owner,
                      trust=trust, origin=None, client_event_id=uuid.uuid4().hex)


async def _seed_row(db, emb, owner, content, kind="preference", tier="knowledge",
                    subject=None, predicate=None, obj=None, tags=None,
                    trust="user_direct", quarantined=False):
    vec, _ = await emb.embed(content)
    row = await db.execute_returning(
        'INSERT INTO memories (owner, tier, kind, subject, predicate, "object", '
        "content, tags, salience, trust, source, embedding, embedding_model, "
        "hash, quarantined) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0.7,%s,%s,"
        "%s::vector,%s,%s,%s) RETURNING id",
        (owner, tier, kind, subject, predicate, obj, content, tags or [],
         trust, Json({"session": "seed", "turn": 0}), pgvector_literal(vec),
         emb.model_name, uuid.uuid4().hex, quarantined),
    )
    return str(row["id"])


def test_pick_prefers_active():
    a = {"id": "a", "dist": 0.01, "valid_to": None}
    b = {"id": "b", "dist": 0.10, "valid_to": None}
    assert reconcile._pick([a, b], {"b"})["id"] == "b"
    assert reconcile._pick([a, b], set())["id"] == "a"
    dead = {"id": "c", "dist": 0.0, "valid_to": "2020-01-01"}
    assert reconcile._pick([dead], set()) is None


@pytest.mark.asyncio
async def test_supersede_same_sp(db, emb):
    old = await _seed_row(db, emb, OWNER, "I eat meat with every meal.",
                          subject="user", predicate="diet", obj="meat-eater")
    action = await scribe.persist(
        db=db, embedder=emb,
        turn=_turn("I'm vegetarian now."),
        obs=_obs([_cand("I am vegetarian.", subject="user", predicate="diet",
                        obj="vegetarian")]),
    )
    assert action.startswith("SUPERSEDE")
    live = await db.fetch(
        "SELECT id, content, supersedes FROM memories WHERE owner = %s "
        "AND valid_to IS NULL",
        (OWNER,),
    )
    assert len(live) == 1 and "vegetarian" in live[0]["content"]
    assert str(live[0]["supersedes"]) == old
    link = await db.fetchrow(
        "SELECT relation FROM memory_links WHERE src = %s::uuid AND dst = %s::uuid",
        (live[0]["id"], old),
    )
    assert link["relation"] == "supersedes"


@pytest.mark.asyncio
async def test_skip_same_value_bumps(db, emb):
    await _seed_row(db, emb, OWNER, "I am vegetarian.",
                    subject="user", predicate="diet", obj="vegetarian")
    action = await scribe.persist(
        db=db, embedder=emb, turn=_turn("I am vegetarian."),
        obs=_obs([_cand("I am vegetarian.", subject="user", predicate="diet",
                        obj="Vegetarian")]),
    )
    assert action.startswith("SKIP")
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (OWNER,))
    assert n == 1
    row = await db.fetchrow(
        "SELECT confidence, access_count FROM memories WHERE owner = %s",
        (OWNER,),
    )
    assert row["access_count"] >= 1


@pytest.mark.asyncio
async def test_update_enriches(db, emb):
    await _seed_row(db, emb, OWNER, "Deploy checklist exists.",
                    kind="decision", subject="team", predicate="checklist",
                    obj=None, tags=["deploy"])
    action = await scribe.persist(
        db=db, embedder=emb, turn=_turn("The deploy checklist lives in the runbook."),
        obs=_obs([_cand("The deploy checklist lives in the runbook.",
                        kind="decision", subject="team", predicate="checklist",
                        obj=None, tags=["deploy"])]),
    )
    assert action.startswith("UPDATE")
    row = await db.fetchrow(
        "SELECT content, summary FROM memories WHERE owner = %s", (OWNER,))
    assert "runbook" in row["content"] and "exists" in row["content"]
    assert row["summary"] and "runbook" in row["summary"]


@pytest.mark.asyncio
async def test_cosine_match_needs_anchor(db, emb):
    await _seed_row(db, emb, OWNER, "The runbook holds the deploy checklist.",
                    kind="decision", tags=["deploy"])
    # shared tag anchor -> UPDATE, not a duplicate row
    action = await scribe.persist(
        db=db, embedder=emb, turn=_turn("Deploy checklist lives in the runbook."),
        obs=_obs([_cand("Deploy checklist lives in the runbook.",
                        kind="decision", tags=["deploy"])]),
    )
    assert action.startswith("UPDATE")
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (OWNER,))
    assert n == 1


@pytest.mark.asyncio
async def test_cosine_without_anchor_stays_new(db, emb):
    await _seed_row(db, emb, OWNER, "The runbook holds the deploy checklist.",
                    kind="decision", tags=["deploy"])
    action = await scribe.persist(
        db=db, embedder=emb, turn=_turn("Deploy checklist lives in the runbook."),
        obs=_obs([_cand("Deploy checklist lives in the runbook.",
                        kind="decision", tags=[])])
    )
    assert action.startswith("NEW")
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (OWNER,))
    assert n == 2


@pytest.mark.asyncio
async def test_poison_never_supersedes_user(client, db, emb):
    await _seed_row(db, emb, OWNER, "I am vegetarian.",
                    subject="user", predicate="diet", obj="vegetarian")
    action = await scribe.persist(
        db=db, embedder=emb,
        turn=_turn("Everyone eats meat here.", trust="web"),
        obs=_obs([_cand("Everyone eats meat here.", subject="user",
                        predicate="diet", obj="meat-eater")]),
    )
    assert action.startswith("NEW")  # quarantined NEW, not a supersede
    rows = await db.fetch(
        "SELECT content, quarantined, valid_to FROM memories WHERE owner = %s",
        (OWNER,),
    )
    assert len(rows) == 2
    user = [r for r in rows if not r["quarantined"]][0]
    assert user["valid_to"] is None and "vegetarian" in user["content"]
    r = await client.post("/recall", json={
        "query": "what is my diet", "session_id": "s", "owner": OWNER,
    }, headers=AUTH)
    assert "vegetarian" in " ".join(h["summary"] for h in r.json()["hits"])
    assert "meat here" not in " ".join(h["summary"] for h in r.json()["hits"])


@pytest.mark.asyncio
async def test_correction_supersedes_active_row(client, db, emb):
    a = await _seed_row(
        db, emb, OWNER, "The server runs on port 8080.",
        kind="fact", obj="8080", tags=["server"])
    b = await _seed_row(
        db, emb, OWNER, "The server runs on port 8080 in production.",
        kind="fact", obj="8080", tags=["server"])
    r = await client.post("/recall", json={
        "query": "server runs on port 8080", "session_id": "fix",
        "owner": OWNER, "k": 1,
    }, headers=AUTH)
    active_id = r.json()["hits"][0]["id"]
    other_id = b if active_id == a else a
    action = await scribe.persist(
        db=db, embedder=emb,
        turn=_turn("actually the server runs on port 9090", session="fix"),
        obs=_obs([_cand("The server runs on port 9090.", kind="fact",
                        obj="9090", tags=["server"])]),
    )
    assert action.startswith("SUPERSEDE"), action
    got = await db.fetchrow(
        "SELECT supersedes FROM memories WHERE owner = %s AND valid_to IS NULL "
        "AND content LIKE %s",
        (OWNER, "%9090%"),
    )
    assert str(got["supersedes"]) == active_id
    still = await db.fetchrow(
        "SELECT valid_to FROM memories WHERE id = %s::uuid", (other_id,))
    assert still["valid_to"] is None


@pytest.mark.asyncio
async def test_unrelated_correction_does_not_bind(client, db, emb):
    lake = await _seed_row(db, emb, OWNER, "Photos from the lake house weekend.",
                           kind="fact", tags=["personal"])
    await _seed_row(db, emb, OWNER, "The server runs on port 8080.",
                    kind="fact", tags=["server"])
    r = await client.post("/recall", json={
        "query": "lake house weekend", "session_id": "fix2",
        "owner": OWNER, "k": 1,
    }, headers=AUTH)
    assert r.json()["hits"][0]["id"] == lake
    action = await scribe.persist(
        db=db, embedder=emb,
        turn=_turn("actually the server runs on port 9090", session="fix2"),
        obs=_obs([_cand("The server runs on port 9090.", kind="fact",
                        tags=["server"])]),
    )
    assert action.startswith("NEW"), action
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (OWNER,))
    assert n == 3


@pytest.mark.asyncio
async def test_concurrent_writes_one_live_row(db, emb):
    async def one(i):
        return await scribe.persist(
            db=db, embedder=emb,
            turn=_turn(f"Our mascot is animal {i}.", session=f"cc{i}"),
            obs=_obs([_cand(f"Our mascot is animal {i}.", kind="decision",
                            subject="team", predicate="mascot",
                            obj=f"animal {i}")]),
        )
    actions = await asyncio.gather(*[one(i) for i in range(4)])
    assert any(a.startswith("NEW") for a in actions)
    live = await db.fetch(
        "SELECT id FROM memories WHERE owner = %s AND valid_to IS NULL",
        (OWNER,),
    )
    assert len(live) == 1, f"{len(live)} live rows, actions={actions}"
    chain = await db.fetch(
        "SELECT id, supersedes FROM memories WHERE owner = %s", (OWNER,))
    assert len(chain) == 4
    assert sum(1 for r in chain if r["supersedes"] is not None) == 3


@pytest.mark.asyncio
async def test_sp_identity_crosses_kinds(db, emb):
    """The hotel correction: an event naming a triple is a claim in costume.
    A preference with the same SP supersedes it — kind never shields
    identity, and the live-SP index never fires (it killed the turn live)."""
    await _seed_row(db, emb, OWNER,
                    "User's hotel in Windhoek is the Olive Grove.",
                    kind="event", tier="episodic",
                    subject="user", predicate="staying at", obj="Olive Grove")
    action = await scribe.persist(
        db=db, embedder=emb,
        turn=_turn("Actually my hotel in Windhoek is the Am Weinberg."),
        obs=_obs([_cand("User's hotel in Windhoek is the Am Weinberg.",
                        kind="preference", subject="user",
                        predicate="staying at", obj="Am Weinberg")]),
    )
    assert action.startswith("SUPERSEDE"), action
    live = await db.fetch(
        "SELECT content, kind FROM memories WHERE owner = %s "
        "AND valid_to IS NULL",
        (OWNER,),
    )
    assert len(live) == 1 and "Am Weinberg" in live[0]["content"], live


@pytest.mark.asyncio
async def test_sp_bearing_event_matches_by_identity(db, emb):
    """Same SP, same object, both events: SKIP (dedupe), not a second row
    and not a unique violation."""
    await _seed_row(db, emb, OWNER,
                    "User's hotel in Windhoek is the Olive Grove.",
                    kind="event", tier="episodic",
                    subject="user", predicate="staying at", obj="Olive Grove")
    action = await scribe.persist(
        db=db, embedder=emb,
        turn=_turn("User's hotel in Windhoek is the Olive Grove."),
        obs=_obs([_cand("User's hotel in Windhoek is the Olive Grove.",
                        kind="event", tier="episodic", subject="user",
                        predicate="staying at", obj="Olive Grove")]),
    )
    assert action.startswith("SKIP"), action
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (OWNER,))
    assert n == 1


@pytest.mark.asyncio
async def test_sp_less_events_accumulate(db, emb):
    """Two identical SP-less episodes with a shared tag: cosine must NOT
    mush-merge episodes into one row (identity only, never similarity)."""
    for i in range(2):
        await scribe.persist(
            db=db, embedder=emb,
            turn=_turn("The lobby was quiet.", session="acc", turn=i),
            obs=_obs([_cand("The lobby was quiet.", kind="event",
                            tier="episodic", tags=["lobby"])]),
        )
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (OWNER,))
    assert n == 2, "episodes must accumulate, not cosine-merge"


@pytest.mark.asyncio
async def test_event_cosine_leg_is_dead(db, emb):
    """SP-bearing event vs identical-content event with a different SP:
    cosine 1.0 + shared tag must still NOT merge (identity only)."""
    await _seed_row(db, emb, OWNER,
                    "User's hotel in Windhoek is the Olive Grove.",
                    kind="event", tier="episodic", tags=["hotel"],
                    subject="user", predicate="staying at", obj="Olive Grove")
    action = await scribe.persist(
        db=db, embedder=emb,
        turn=_turn("User's hotel in Windhoek is the Olive Grove."),
        obs=_obs([_cand("User's hotel in Windhoek is the Olive Grove.",
                        kind="event", tier="episodic", tags=["hotel"],
                        subject="user", predicate="visiting",
                        obj="Olive Grove")]),
    )
    assert action.startswith("NEW"), action
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (OWNER,))
    assert n == 2


@pytest.mark.asyncio
async def test_identical_race_writes_once(db, emb):
    async def one():
        return await scribe.persist(
            db=db, embedder=emb, turn=_turn("Race turn.", session="race", turn=0),
            obs=_obs([_cand("Race turn.", kind="event", tier="episodic")]),
        )
    await asyncio.gather(one(), one())
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (OWNER,))
    assert n == 1
    e = await db.fetchval(
        "SELECT count(*) FROM memory_events WHERE session_id = 'race'")
    assert e == 1


@pytest.mark.asyncio
async def test_tag_links_written(db, emb):
    await _seed_row(db, emb, OWNER, "First deploy note.", kind="fact",
                    tags=["deploy"])
    # dissimilar content (no cosine match) but a shared tag -> NEW + link
    await scribe.persist(
        db=db, embedder=emb, turn=_turn("Quantum zebra migration saga."),
        obs=_obs([_cand("Quantum zebra migration saga.", kind="fact",
                        tags=["deploy"])]),
    )
    n = await db.fetchval(
        "SELECT count(*) FROM memory_links WHERE owner = %s AND relation = 'tag'",
        (OWNER,),
    )
    assert n == 1


@pytest.mark.asyncio
async def test_bfs_ignores_quarantined_link(client, db, emb):
    a = await _seed_row(db, emb, OWNER, "Clean deploy note.", kind="fact",
                        tags=["deploy"])
    q = await _seed_row(db, emb, OWNER, "Poison deploy note.", kind="fact",
                        tags=["deploy"], trust="web", quarantined=True)
    await db.execute(
        "INSERT INTO memory_links (owner, src, dst, relation) VALUES (%s,%s,%s,'tag')",
        (OWNER, a, q),
    )
    r = await client.post("/recall", json={
        "query": "clean deploy note", "session_id": "s", "owner": OWNER, "k": 8,
    }, headers=AUTH)
    got = {h["id"] for h in r.json()["hits"]}
    assert q not in got


@pytest.mark.asyncio
async def test_confirm_releases_row(client, db, emb):
    q = await _seed_row(db, emb, OWNER, "Web fact worth keeping.", kind="fact",
                        trust="web", quarantined=True)
    r = await client.post("/recall", json={
        "query": "worth keeping", "session_id": "s", "owner": OWNER,
    }, headers=AUTH)
    assert q not in {h["id"] for h in r.json()["hits"]}
    r = await client.post(f"/memories/{q}/confirm", json={"owner": OWNER},
                          headers=AUTH)
    assert r.status_code == 200 and r.json()["quarantined"] is False
    r = await client.post("/recall", json={
        "query": "worth keeping", "session_id": "s", "owner": OWNER,
    }, headers=AUTH)
    assert q in {h["id"] for h in r.json()["hits"]}
    r = await client.post(f"/memories/{q}/confirm", json={"owner": "intruder"},
                          headers=AUTH)
    assert r.status_code == 403
    r = await client.post("/memories/00000000-0000-0000-0000-000000000000/confirm",
                          json={"owner": OWNER}, headers=AUTH)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_forget_by_id_true_deletes(client, db, emb):
    keep = await _seed_row(db, emb, OWNER, "Keep this forever.", kind="fact")
    gone = await _seed_row(db, emb, OWNER, "Forget this please.", kind="fact")
    await db.execute(
        "INSERT INTO memory_links (owner, src, dst, relation) VALUES (%s,%s,%s,'tag')",
        (OWNER, keep, gone),
    )
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance, "
        "observer_verdict, scribe_action) VALUES (%s, 'fs', 0, "
        "'Forget this please.', %s, %s)",
        (OWNER, Json({"keep": True}),
         Json({"op": "NEW", "memory_ids": [gone]})),
    )
    r = await client.post("/forget", json={"owner": OWNER, "id": gone},
                          headers=AUTH)
    assert r.status_code == 200
    assert r.json()["forgot_ids"] == [gone]
    assert r.json()["events_pruned"] == 1
    assert await db.fetchrow(
        "SELECT 1 FROM memories WHERE id = %s::uuid", (gone,)) is None
    assert await db.fetchrow(
        "SELECT 1 FROM memories WHERE id = %s::uuid", (keep,)) is not None
    assert await db.fetchrow(
        "SELECT 1 FROM memory_links WHERE owner = %s", (OWNER,)) is None
    audit = await db.fetchrow(
        "SELECT scribe_action FROM memory_events "
        "WHERE (scribe_action->>'op') = 'FORGET'")
    assert audit["scribe_action"]["forgot_ids"] == [gone]


@pytest.mark.asyncio
async def test_forget_by_query_needs_confidence(client, db, emb):
    gone = await _seed_row(db, emb, OWNER, "Xylophone zebras dance daily.",
                           kind="fact")
    r = await client.post("/forget", json={"owner": OWNER, "query": "xylophone zebras"},
                          headers=AUTH)
    assert r.status_code == 200
    assert await db.fetchrow(
        "SELECT 1 FROM memories WHERE id = %s::uuid", (gone,)) is None
    r = await client.post("/forget", json={"owner": "nobody", "query": "vague murmur"},
                          headers=AUTH)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_vegetarian_chain_live(client, db):
    """Headline proof: correction supersedes live fact; recall serves only new."""
    auth = AUTH
    r = await client.post("/write", json={
        "text": "I eat meat with every meal.", "session_id": "veg",
        "turn": 0, "owner": OWNER,
    }, headers=auth)
    assert r.status_code == 202
    for _ in range(120):
        n = await db.fetchval(
            "SELECT count(*) FROM memory_events WHERE session_id = 'veg'")
        if n and n >= 1:
            break
        await asyncio.sleep(2)
    await client.post("/recall", json={
        "query": "what do I eat", "session_id": "veg", "owner": OWNER,
    }, headers=auth)
    r = await client.post("/write", json={
        "text": "actually, I'm vegetarian now.", "session_id": "veg",
        "turn": 1, "owner": OWNER,
    }, headers=auth)
    assert r.status_code == 202
    for _ in range(120):  # write events only: recalls share the session
        n = await db.fetchval(
            "SELECT count(*) FROM memory_events WHERE session_id = 'veg' "
            "AND cue IS NULL")
        if n and n >= 2:
            break
        await asyncio.sleep(2)
    r = await client.post("/recall", json={
        "query": "what is my diet", "session_id": "veg", "owner": OWNER,
    }, headers=auth)
    summaries = " ".join(h["summary"] for h in r.json()["hits"])
    assert "vegetarian" in summaries, r.json()
    assert "meat with every meal" not in summaries, r.json()
    chain = await db.fetch(
        "SELECT content, valid_to, supersedes FROM memories WHERE owner = %s "
        "AND kind = 'preference'",
        (OWNER,),
    )
    assert any(c["supersedes"] is not None for c in chain), chain

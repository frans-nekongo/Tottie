"""/write over real HTTP: 202 immediacy, curation lands, idempotent retries,
chitchat skips, 401/422 shapes. Live Meta calls — the slow honest tests."""
import asyncio
import uuid

import pytest
from psycopg.types.json import Json

from app.config import Settings
from app.db import pgvector_literal
from app.embeddings import Embedder

AUTH = {"Authorization": "Bearer test-token"}


async def _seed_sp(db, owner, content, subject, predicate, obj):
    """One SP-stamped row (production shape: LLM-scribed rows always carry
    SP). The seed text is exact, so pair cosines measured offline hold."""
    emb = Embedder(Settings())
    vec, _ = await emb.embed(content)
    row = await db.execute_returning(
        'INSERT INTO memories (owner, tier, kind, subject, predicate, "object", '
        'content, trust, source, embedding, embedding_model, hash) '
        'VALUES (%s,\'knowledge\',\'fact\',%s,%s,%s,%s,\'user_direct\',%s,'
        '%s::vector,%s,%s) RETURNING id',
        (owner, subject, predicate, obj, content,
         Json({"session": "seed", "turn": 0}), pgvector_literal(vec),
         emb.model_name, uuid.uuid4().hex),
    )
    return str(row["id"])


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
async def test_write_correction_journals_despite_familiarity(client, db):
    """Fix 1 (CorrectionSniffer): a CORRECTION is Bayesian surprise, never
    Shannon familiarity. Live Amara pair: the Friday->Wednesday move scored
    0.81 >= 0.80 and was swallowed as 'already known'. Now it bypasses the
    gate and reconciles against the anchor-matched row. The op is UPDATE
    when the clerk scribes SP-less (history appended, summary carries
    current truth) and SUPERSEDE when it scribes SP triples (old row
    retired, chain linked) — the LLM picks the shape, so the test pins the
    invariants, never a duplicate, never a loss: exactly one live row,
    Wednesday current, Friday preserved, recall serves Wednesday. Live Meta."""
    ow = "w1corr"
    r = await client.post("/write", json=_payload(
        text="The Namib Roasters rebrand is due Friday.",
        session_id="w1corr", owner=ow, turn=0), headers=AUTH)
    assert r.status_code == 202
    for _ in range(120):
        n = await db.fetchval(
            "SELECT count(*) FROM memories WHERE owner = %s", (ow,))
        if n and n >= 1:
            break
        await asyncio.sleep(1)
    assert n == 1, "fact turn never curated"
    r = await client.post("/write", json=_payload(
        text="Actually the deadline moved to next Wednesday.",
        session_id="w1corr", owner=ow, turn=1), headers=AUTH)
    assert r.status_code == 202
    ev = None
    for _ in range(120):
        ev = await db.fetchrow(
            "SELECT scribe_action FROM memory_events "
            "WHERE session_id = 'w1corr' AND turn = 1")
        if ev:
            break
        await asyncio.sleep(1)
    assert ev is not None, "correction turn never curated"
    op = ev["scribe_action"]["op"]
    assert op in ("UPDATE", "SUPERSEDE"), ev["scribe_action"]
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s "
        "AND valid_to IS NULL", (ow,))
    assert n == 1, f"duplicated instead of reconciled (n={n})"
    live = await db.fetchrow(
        "SELECT id, content, summary, supersedes FROM memories "
        "WHERE owner = %s AND valid_to IS NULL", (ow,))
    assert "Wednesday" in (live["content"] or ""), live  # current truth
    if op == "UPDATE":
        assert "Wednesday" in (live["summary"] or ""), live
        assert "Friday" in (live["content"] or ""), live  # history kept
    else:
        dead = await db.fetchrow(
            "SELECT id, content FROM memories WHERE owner = %s "
            "AND valid_to IS NOT NULL", (ow,))
        assert dead is not None, "supersede retired nothing"
        assert "Friday" in (dead["content"] or ""), dead  # history kept
        assert str(live["supersedes"]) == str(dead["id"]), live
    r = await client.post("/recall", json={
        "query": "When is the Namib Roasters rebrand due?",
        "session_id": "w1corr", "owner": ow}, headers=AUTH)
    assert r.status_code == 200
    assert "Wednesday" in (r.json()["card"] or ""), r.json()["card"]


@pytest.mark.asyncio
async def test_write_unmarked_move_supersedes_despite_wording(client, db):
    """G4: the Friday move WITHOUT correction markers must still update.
    The turn (cos 0.89, "moved" polarity trip) rides the verified lane,
    which bypasses
    the string subject gate — scribe wording varies ("rebrand" vs
    "deadline") while the entity is one. Same invariants as the marked
    twin: one live row, Wednesday current, Friday kept. Live Meta."""
    ow = f"w1nli_{uuid.uuid4().hex[:8]}"
    await _seed_sp(db, ow, "The Namib Roasters rebrand is due Friday.",
                   "namib roasters rebrand", "due", "friday")
    r = await client.post("/write", json=_payload(
        text="The deadline for the Namib Roasters rebrand moved from "
             "Friday to next Wednesday.",
        session_id=ow, turn=0, owner=ow), headers=AUTH)
    assert r.status_code == 202
    ev = None
    for _ in range(120):
        ev = await db.fetchrow(
            "SELECT observer_verdict, scribe_action FROM memory_events "
            "WHERE owner = %s AND turn = 0", (ow,))
        if ev:
            break
        await asyncio.sleep(1)
    assert ev is not None, "move turn never curated"
    assert ev["observer_verdict"]["keep"] is True
    assert "contra" in ev["observer_verdict"]["reason"], \
        ev["observer_verdict"]
    op = ev["scribe_action"]["op"]
    assert op in ("UPDATE", "SUPERSEDE"), ev["scribe_action"]
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s "
        "AND valid_to IS NULL", (ow,))
    assert n == 1, f"duplicated instead of reconciled (n={n})"
    live = await db.fetchrow(
        "SELECT content, summary, supersedes FROM memories "
        "WHERE owner = %s AND valid_to IS NULL", (ow,))
    assert "Wednesday" in (live["content"] or ""), live
    if op == "SUPERSEDE":
        dead = await db.fetchrow(
            "SELECT content FROM memories WHERE owner = %s "
            "AND valid_to IS NOT NULL", (ow,))
        assert "Friday" in (dead["content"] or ""), dead


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

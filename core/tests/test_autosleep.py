"""Auto-sleep: consolidation is a heartbeat, not a button.

owners_due fires only for owners gone idle past sleep_idle_min while
holding 2+ live, unranked episodes newer than their last CONSOLIDATE.
States are crafted with SQL timestamps — deterministic, no waiting on
real clocks. auto_tick never raises: one bad owner cannot kill the loop.
"""
import uuid

import pytest
from psycopg.types.json import Json

from app.agents import consolidate
from app.config import Settings, get_settings
from app.embeddings import Embedder


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


async def _ep(db, owner, n=2):
    for i in range(n):
        await db.execute(
            "INSERT INTO memories (owner, tier, kind, content, hash) "
            "VALUES (%s,'episodic','event',%s,%s)",
            (owner, f"ep {i} {uuid.uuid4().hex}", uuid.uuid4().hex),
        )


async def _ev(db, owner, op="NEW", age_min=0, turn=0):
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance, "
        "observer_verdict, scribe_action, ts) "
        "VALUES (%s,'s',%s,'x',%s,%s,now() - make_interval(mins => %s))",
        (owner, turn, Json({"keep": True}), Json({"op": op}), age_min),
    )


@pytest.mark.asyncio
async def test_owners_due_matrix(db):
    s = get_settings()
    idle = await _mk(db, "due", eps=2, ev_age=60)
    await _mk(db, "active", eps=2, ev_age=0)
    await _mk(db, "thin", eps=1, ev_age=60)
    await _mk(db, "slept", eps=2, ev_age=60, consolidated=True)
    due = await consolidate.owners_due(db, s)
    assert due == [idle], due


async def _mk(db, tag, eps, ev_age, consolidated=False):
    ow = f"sleep_{tag}_{uuid.uuid4().hex[:6]}"
    await _ep(db, ow, eps)
    await _ev(db, ow, age_min=ev_age)
    if consolidated:
        await _ev(db, ow, op="CONSOLIDATE", age_min=ev_age, turn=1)
        # episodes predate the consolidate: already dreamed
        await db.execute(
            "UPDATE memories SET created_at = now() - make_interval(mins => %s) "
            "WHERE owner = %s",
            (ev_age + 5, ow),
        )
    return ow


@pytest.mark.asyncio
async def test_auto_tick_never_raises(db):
    """A dead pool inside the tick returns [], not an exception — the
    heartbeat survives real outages. No mocks: the pool is genuinely
    closed first (function-scoped fixture, nothing else suffers)."""
    s = get_settings()
    await db.close()
    assert await consolidate.auto_tick(db=db, embedder=None, settings=s) == []


@pytest.mark.asyncio
async def test_auto_tick_sleeps_due_owner(db, emb):
    """End to end without the clock: a due owner gets a real CONSOLIDATE
    event and distilled rows. Live Meta for the semanticise call."""
    from tests.test_recall import seed

    ow = f"sleep_e2e_{uuid.uuid4().hex[:6]}"
    await seed(db, emb, ow, [
        {"name": "e1", "tier": "episodic", "content": "Anna paid for groceries."},
        {"name": "e2", "tier": "episodic", "content": "Ben paid for electricity."},
    ])
    await _ev(db, ow, age_min=60)
    s = get_settings()
    assert ow in await consolidate.owners_due(db, s)
    slept = await consolidate.auto_tick(db=db, embedder=emb, settings=s)
    assert slept == [ow]
    ev = await db.fetchrow(
        "SELECT scribe_action FROM memory_events WHERE owner = %s "
        "AND scribe_action->>'op' = 'CONSOLIDATE'",
        (ow,),
    )
    assert ev is not None, "no CONSOLIDATE ledger event"
    assert ow not in await consolidate.owners_due(db, s), "still due after sleep"

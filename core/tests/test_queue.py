"""Typed job queue: turn wrapping, handler dispatch, unknown-kind safety.

Deterministic: stub handlers, real asyncio workers, no LLM, no DB.
"""
import asyncio

import pytest

from app.queue import (
    LINK_ROW,
    RECONCILE_TURN,
    Job,
    WorkerTurn,
    WriteQueue,
)


def _turn():
    return WorkerTurn(
        text="Queue the turn.", session_id="jq", turn=0, owner="jq",
        trust="user_direct", origin=None, client_event_id="",
    )


def test_enqueue_nowait_wraps_reconcile_turn():
    q = WriteQueue(None, db=None, embedder=None)
    eid = q.enqueue_nowait(_turn())
    assert q.depth == 1
    job: Job = q._q.get_nowait()
    assert job.kind == RECONCILE_TURN
    assert job.turn.text == "Queue the turn."
    assert job.client_event_id == eid
    assert job.turn.client_event_id == eid


@pytest.mark.asyncio
async def test_dispatch_runs_registered_handler():
    q = WriteQueue(None, db=None, embedder=None, workers=1)
    ran = asyncio.Event()
    seen = {}

    async def handler(*, db, embedder, settings, job):
        seen["kind"] = job.kind
        seen["payload"] = job.payload
        ran.set()

    q.register(LINK_ROW, handler)
    await q.start()
    try:
        q.enqueue_job(LINK_ROW, payload={"memory_id": "abc"})
        await asyncio.wait_for(ran.wait(), timeout=5)
    finally:
        await q.stop()
    assert seen == {"kind": LINK_ROW, "payload": {"memory_id": "abc"}}


@pytest.mark.asyncio
async def test_unknown_kind_counts_and_survives():
    q = WriteQueue(None, db=None, embedder=None, workers=1)
    await q.start()
    try:
        q.enqueue_job("nope_not_a_kind")
        for _ in range(50):
            if q.unknown_kind:
                break
            await asyncio.sleep(0.05)
    finally:
        await q.stop()
    assert q.unknown_kind == 1
    assert q.depth == 0

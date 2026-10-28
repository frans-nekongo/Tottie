"""Persist observations: one transaction per turn, reconcile per candidate.

Shapes follow schema.sql exactly. Turn atomicity: duplicate-turn check,
all candidate mutations, and the event commit together or roll back
together. On a unique violation (lost an SP race with a concurrent twin)
the whole turn retries once — the retry then sees the twin's row and
reconciles against it instead of duplicating it.
"""
import logging

from psycopg.errors import UniqueViolation
from psycopg.types.json import Json

from . import cues, reconcile

log = logging.getLogger("tottie.scribe")


async def persist(*, db, embedder, turn, obs) -> str:
    if not obs.keep:
        try:
            await _event(db, turn, obs, op="SKIP", ops=[], memory_ids=[])
        except UniqueViolation:
            return "SKIP duplicate-turn"  # twin recorded the skip first
        return f"SKIP {obs.verdict}"
    embedded = []
    for cand in obs.candidates:
        vec, _ = await embedder.embed(cand["content"])
        embedded.append((cand, vec))
    last: Exception | None = None
    for _ in range(4):
        try:
            async with db.transaction() as conn:
                return await _persist_txn(
                    conn, db, turn, obs, embedded, embedder.model_name
                )
        except UniqueViolation as e:
            last = e  # twin won the race; retry reconciles against it
            log.info("turn raced a twin; retrying")
    raise last  # pragma: no cover - five-plus concurrent identical SP writers


async def _persist_txn(conn, db, turn, obs, embedded, model) -> str:
    cur = await conn.execute(
        "SELECT 1 FROM memory_events WHERE session_id = %s AND turn = %s "
        "AND utterance = %s",
        (turn.session_id, turn.turn, turn.text),
    )
    if await cur.fetchone():
        return "SKIP duplicate-turn"
    cue = cues.classify(turn.text)
    active = (
        reconcile.get_active(turn.owner, turn.session_id)
        if cue.type == "CORRECTION"
        else set()
    )
    ops = []
    for cand, vec in embedded:
        rec = await reconcile.apply_candidate(
            conn, turn=turn, obs=obs, cand=cand, vec=vec, model=model,
            floor=db._settings.reconcile_cosine,
            active_floor=db._settings.active_cosine, active=active,
        )
        ops.append(rec)
    memory_ids = [o["memory_id"] for o in ops]
    op = next((o["op"] for o in ops if o["op"] != "SKIP"), "SKIP")
    if obs.raw_fallback:
        op = "RAW"
    await _event_txn(conn, turn, obs, op=op, ops=ops, memory_ids=memory_ids)
    return f"{op} n={len(memory_ids)} {obs.verdict}"


async def _event(db, turn, obs, *, op: str, ops: list, memory_ids: list[str]) -> None:
    await db.execute(
        "INSERT INTO memory_events (session_id, turn, utterance, observer_verdict, "
        "scribe_action, latency_ms, tokens) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (
            turn.session_id, turn.turn, turn.text,
            Json({
                "keep": obs.keep, "salience": obs.salience,
                "surprise": obs.surprise, "reason": obs.verdict,
                "candidates": obs.candidates,
            }),
            Json({
                "op": op, "ops": ops, "n": len(memory_ids),
                "memory_ids": memory_ids,
                "superseded_ids": [
                    o["superseded_id"] for o in ops if o.get("superseded_id")
                ],
                "provider": obs.provider,
            }),
            obs.latency_ms, obs.prompt_tokens + obs.completion_tokens,
        ),
    )


async def _event_txn(conn, turn, obs, *, op, ops, memory_ids) -> None:
    await conn.execute(
        "INSERT INTO memory_events (session_id, turn, utterance, observer_verdict, "
        "scribe_action, latency_ms, tokens) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (
            turn.session_id, turn.turn, turn.text,
            Json({
                "keep": obs.keep, "salience": obs.salience,
                "surprise": obs.surprise, "reason": obs.verdict,
                "candidates": obs.candidates,
            }),
            Json({
                "op": op, "ops": ops, "n": len(memory_ids),
                "memory_ids": memory_ids,
                "superseded_ids": [
                    o["superseded_id"] for o in ops if o.get("superseded_id")
                ],
                "provider": obs.provider,
            }),
            obs.latency_ms, obs.prompt_tokens + obs.completion_tokens,
        ),
    )

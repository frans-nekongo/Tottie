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

from . import cues, reconcile, retrieve

log = logging.getLogger("tottie.scribe")


async def _maybe_register_intention(db, turn) -> None:
    """A "remind me..." turn is a prospective registration, not (only) an
    episode. Runs on the write path so /write setup registers exactly like
    /chat recall does; register_reminder is idempotent across both."""
    if cues.classify(turn.text).type != "COMMAND":
        return
    draft = cues.parse_reminder(turn.text)
    if draft:
        await retrieve.register_reminder(db, turn.owner, draft)


async def persist(*, db, embedder, turn, obs, stages=None) -> str:
    from ..queue import Stages as _Stages  # lazy: queue imports scribe
    stages = stages or _Stages()
    await _maybe_register_intention(db, turn)
    if not obs.keep:
        try:
            await _event(db, turn, obs, op="SKIP", ops=[], memory_ids=[],
                         stages=stages)
        except UniqueViolation:
            return "SKIP duplicate-turn"  # twin recorded the skip first
        return f"SKIP {obs.verdict}"
    embedded = []
    with stages.span("embed_candidates"):
        for cand in obs.candidates:
            vec, _ = await embedder.embed(cand["content"])
            embedded.append((cand, vec))
    last: Exception | None = None
    for _ in range(4):
        try:
            async with db.transaction() as conn:
                return await _persist_txn(
                    conn, db, turn, obs, embedded, embedder.model_name,
                    stages=stages,
                )
        except UniqueViolation as e:
            last = e  # twin won the race; retry reconciles against it
            log.info("turn raced a twin; retrying")
    raise last  # pragma: no cover - a same-slot collision that survived
    # retries means a true race (G7 co-retire handles the visible case)


async def _persist_txn(conn, db, turn, obs, embedded, model, stages=None) -> str:
    cur = await conn.execute(
        "SELECT 1 FROM memory_events WHERE owner = %s AND session_id = %s "
        "AND turn = %s AND utterance_hash = md5(%s)",
        (turn.owner, turn.session_id, turn.turn, turn.text),
    )
    if await cur.fetchone():
        return "SKIP duplicate-turn"
    cue = cues.classify(turn.text)
    target = getattr(obs, "correction_target", None)
    is_corr = cue.type == "CORRECTION" or target is not None
    # Explicit = human-marked reversal (cue, polarity lexicon, F2a bypass).
    # A bare verifier target is implicit: NLI misfires ~1.00 on
    # same-template rows, so reconcile re-verifies those with the
    # opposition gate instead of trusting the route.
    correction_explicit = (
        cue.type == "CORRECTION"
        or getattr(obs, "correction_explicit", False)
    )
    active = (
        reconcile.get_active(turn.owner, turn.session_id)
        if is_corr
        else set()
    )
    # Labile registrations match at the active floor; otherwise a
    # CORRECTION falls back to the recent-session pool with anchor-gated
    # matching (kept separate: different rule, different floor). A
    # verifier-caught contradiction names its target exactly (G1 fix):
    # no pool guessing, works across days, not just recent turns.
    correction_pool: set[str] = set()
    if target is not None:
        correction_pool = {target}
    elif cue.type == "CORRECTION" and not active:
        correction_pool = await reconcile.recent_session_ids(
            conn, turn.owner, turn.session_id,
            limit=reconcile.RECENT_SESSION_LIMIT)
    # Session-wide elimination: a session pool holding exactly one row
    # is the only thing the correction could mean (w1corr). F2a {target}
    # singletons don't count — a similarity target is a guess. Active
    # (labile) matches don't count either: every recall pollutes the
    # active set, so recalled rows still need entity evidence to die.
    pool_singleton_session = (
        target is None and len(correction_pool) == 1)
    ops = []
    with stages.span("reconcile"):
        for cand, vec in embedded:
            rec = await reconcile.apply_candidate(
                conn, turn=turn, obs=obs, cand=cand, vec=vec, model=model,
                floor=db._settings.reconcile_cosine,
                active_floor=db._settings.active_cosine, active=active,
                correction_pool=correction_pool,
                correction_explicit=correction_explicit,
                pool_singleton_session=pool_singleton_session,
            )
            ops.append(rec)
    memory_ids = [o["memory_id"] for o in ops]
    op = next((o["op"] for o in ops if o["op"] != "SKIP"), "SKIP")
    if obs.raw_fallback:
        op = "RAW"
    with stages.span("event_write"):
        await _event_txn(conn, turn, obs, op=op, ops=ops,
                         memory_ids=memory_ids, stages=stages)
    return f"{op} n={len(memory_ids)} {obs.verdict}"


async def _event(db, turn, obs, *, op: str, ops: list, memory_ids: list[str],
               stages=None) -> None:
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance, "
        "utterance_hash, observer_verdict, scribe_action, latency_ms, tokens,"
        " stage_ms) "
        "VALUES (%s,%s,%s,%s,md5(%s),%s,%s,%s,%s,%s)",
        (
            turn.owner, turn.session_id, turn.turn, turn.text, turn.text,
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
            Json(stages.as_dict() if stages is not None else {}),
        ),
    )


async def _event_txn(conn, turn, obs, *, op, ops, memory_ids,
                   stages=None) -> None:
    await conn.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance, "
        "utterance_hash, observer_verdict, scribe_action, latency_ms, tokens,"
        " stage_ms) "
        "VALUES (%s,%s,%s,%s,md5(%s),%s,%s,%s,%s,%s)",
        (
            turn.owner, turn.session_id, turn.turn, turn.text, turn.text,
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
            Json(stages.as_dict() if stages is not None else {}),
        ),
    )

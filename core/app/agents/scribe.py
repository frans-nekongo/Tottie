"""Persist observations: embed candidates, write memories + the turn's event.

Shapes follow schema.sql exactly: memories.source is one JSONB context object,
memory_events carries utterance + JSONB verdict/action + latency/tokens.
W1 scope: NEW rows only (reconcile ops land in W3). Quarantine policy applies
from day one: low-trust identity/convention/decision/lesson rows are stored
quarantined — visible, never injected — until confirmed (endpoint in W3).
Idempotency: row hash = sha256(session:turn:content); retries hit
ON CONFLICT DO NOTHING, and duplicate turns short-circuit before writing.
"""
import hashlib
import logging

from psycopg.types.json import Json

from ..db import pgvector_literal

log = logging.getLogger("tottie.scribe")

QUARANTINE_TRUSTS = {"tool", "web", "model_inferred"}
QUARANTINE_KINDS = {"identity", "convention", "decision", "lesson"}


def row_hash(session_id: str, turn: int, content: str) -> str:
    return hashlib.sha256(
        f"{session_id}:{turn}:{content}".encode()
    ).hexdigest()[:32]


async def persist(*, db, embedder, turn, obs) -> str:
    if not obs.keep:
        await _event(db, turn, obs, op="SKIP", memory_ids=[])
        return f"SKIP {obs.verdict}"
    dup = await db.fetchval(
        "SELECT 1 FROM memory_events WHERE session_id = %s AND turn = %s "
        "AND utterance = %s",
        (turn.session_id, turn.turn, turn.text),
    )
    if dup:
        return "SKIP duplicate-turn"
    memory_ids: list[str] = []
    for cand in obs.candidates:
        vec, _ = await embedder.embed(cand["content"])
        quarantined = (
            turn.trust in QUARANTINE_TRUSTS and cand["kind"] in QUARANTINE_KINDS
        )
        row = await db.execute_returning(
            'INSERT INTO memories (owner, tier, kind, subject, predicate, "object", '
            "content, tags, principle, salience, surprise, trust, source, "
            "embedding, embedding_model, hash, quarantined, needs_curation) VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s,%s,%s) "
            "ON CONFLICT (owner, hash) WHERE hash IS NOT NULL "
            "DO NOTHING RETURNING id",
            (
                turn.owner, cand["tier"], cand["kind"], cand["subject"],
                cand["predicate"], cand["object"], cand["content"], cand["tags"],
                cand["principle"], obs.salience, obs.surprise, turn.trust,
                Json({
                    "session": turn.session_id, "turn": turn.turn,
                    "origin": turn.origin,
                    "client_event_id": turn.client_event_id,
                }),
                pgvector_literal(vec), embedder.model_name,
                row_hash(turn.session_id, turn.turn, cand["content"]),
                quarantined, obs.raw_fallback,
            ),
        )
        if row is None:  # lost a race with our own retry: look up the winner
            row = await db.fetchrow(
                "SELECT id FROM memories WHERE owner = %s AND hash = %s",
                (turn.owner, row_hash(turn.session_id, turn.turn, cand["content"])),
            )
        memory_ids.append(str(row["id"]))
    op = "RAW" if obs.raw_fallback else "NEW"
    await _event(db, turn, obs, op=op, memory_ids=memory_ids)
    return f"{op} n={len(memory_ids)} {obs.verdict}"


async def _event(db, turn, obs, *, op: str, memory_ids: list[str]) -> None:
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
                "op": op, "n": len(memory_ids), "memory_ids": memory_ids,
                "provider": obs.provider,
            }),
            obs.latency_ms, obs.prompt_tokens + obs.completion_tokens,
        ),
    )

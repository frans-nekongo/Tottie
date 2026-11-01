"""The Ranker: forgetting by the retrievability curve, not heuristics.

R(t) = exp(-age_days / stability). Each sweep sets ranked_out from the
curve in BOTH directions: stale rows (R < RANK_FLOOR) rank out of
ambient legs, and practiced rows (serve bumps stability, R recovers)
rank back in. Ranked-out rows stay revivable via the probe replay
path — ranked_out is invisible, never deleted.

Runs as a RANK_SWEEP job (sleep heartbeat). Pure SQL + math: no NLI,
no LLM, deterministic.
"""
import logging

from psycopg.types.json import Json

log = logging.getLogger("tottie.ranker")

RANK_FLOOR = 0.05


def retrievability(age_days: float, stability: float) -> float:
    import math
    if stability <= 0:
        return 0.0
    return math.exp(-max(0.0, age_days) / stability)


async def run_sweep(*, db, embedder, settings, owner: str) -> dict:
    rows = await db.fetch(
        "SELECT id, ranked_out, "
        "EXTRACT(EPOCH FROM (now() - created_at)) / 86400.0 AS age_days, "
        "stability FROM memories WHERE owner = %s AND valid_to IS NULL",
        (owner,),
    )
    out, back = 0, 0
    for r in rows:
        alive = retrievability(float(r["age_days"] or 0.0),
                               float(r["stability"] or 0.0)) >= RANK_FLOOR
        should_rank = not alive
        if bool(r["ranked_out"]) == should_rank:
            continue
        await db.execute(
            "UPDATE memories SET ranked_out = %s WHERE id = %s::uuid",
            (should_rank, str(r["id"])),
        )
        if should_rank:
            out += 1
        else:
            back += 1
    summary = {"ranked_out": out, "ranked_back": back,
               "rows": len(rows)}
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance, "
        "observer_verdict, scribe_action) VALUES (%s,'sweep',NULL,%s,%s,%s)",
        (owner, f"ranker sweep: {out} out, {back} back of {len(rows)} rows",
         Json({"keep": True, "reason": "ranker sweep"}),
         Json({"op": "RANK_SWEEP", **summary})),
    )
    log.info("ranker swept %s: %s", owner, summary)
    return summary


async def handle_job(*, db, embedder, settings, job) -> dict:
    """Queue adapter: RANK_SWEEP jobs carry {owner} in the payload."""
    return await run_sweep(
        db=db, embedder=embedder, settings=settings,
        owner=job.payload.get("owner", settings.owner),
    )

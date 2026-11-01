"""The Updater: background truth maintenance. Two passes over one owner's
live rows, newest-wins everywhere:

1. Dup pass: pairs at cosine >= DUP_COSINE are the same fact twice
   (G6a emits several; cross-partition twins meet here). The older
   retires with a `duplicate` link to the keeper.
2. Contra pass: last SWEEP_ROWS live rows each check their K nearest
   neighbors above CONTRA_NEIGHBOR with the NLI verifier; a
   SYMMETRIC contradiction (p_contra >= threshold in BOTH directions)
   retires the older row with a `supersedes` link. One-directional
   fire is progression, not contradiction (request -> fulfillment
   reads contra forward but neutral back). Catches what the write
   path missed (G5 terse reversals).

Within-partition only (same quarantined value): merging across the
trust boundary would launder poison into trusted rows. Short
transactions, row locks, id ordered to avoid deadlocks; re-checks
liveness after locking so concurrent sweeps never double-retire.

Two hard lessons from the first live run (70 rows wrongly retired,
rolled back): the NLI reads far-apart pairs as contradiction ~1.00
(the int8 quirk), so the neighbor floor matches the write path at
0.80, never lower; and a sweep retires at most MAX_RETIRE rows, then
stops with capped=true in the ledger. An auto-deleting agent without
a cap is a loaded gun.
"""
import logging

from psycopg.types.json import Json

from .. import nli
from ..db import pgvector_literal
from . import reconcile

log = logging.getLogger("tottie.updater")

DUP_COSINE = 0.95
CONTRA_NEIGHBOR = 0.80
SWEEP_ROWS = 100
NEIGHBOR_K = 5
PAIR_CAP = 300
MAX_RETIRE = 15
# Speech acts describe utterances that happened ("requested X", "said Y"):
# immutable history, never state claims. Neither side of a speech-act
# pair can contradict (live: "requested a tracker" vs "built it" read
# symmetric-contra 1.00/0.99 and wrongly retired the request).
SPEECH_VERBS = {"requested", "asked", "told", "said"}


def _is_speech_act(content: str, predicate: str | None) -> bool:
    if (predicate or "").strip().lower() in SPEECH_VERBS:
        return True
    words = set((content or "").lower().split())
    return not SPEECH_VERBS.isdisjoint(words)


async def _retire(db, *, owner, keeper_id, dead_id, relation, reason) -> None:
    async with db.transaction() as conn:
        rows = await conn.execute(
            "SELECT id, valid_to FROM memories WHERE id = ANY(%s::uuid[]) "
            "ORDER BY id FOR UPDATE",
            ([keeper_id, dead_id],),
        )
        live = {str(r["id"]) for r in await rows.fetchall()
                if r["valid_to"] is None}
        if keeper_id not in live or dead_id not in live:
            return False
        await conn.execute(
            "UPDATE memories SET valid_to = now() WHERE id = %s::uuid",
            (dead_id,),
        )
        await reconcile._link(
            conn, owner=owner, src=keeper_id, dst=dead_id,
            relation=relation, weight=1.0, reason=reason,
        )
    return True


async def _dup_pairs(db, owner, limit):
    return await db.fetch(
        "SELECT a.id AS a, b.id AS b, "
        "1 - (a.embedding <=> b.embedding) AS cos, "
        "a.created_at AS a_ts, b.created_at AS b_ts "
        "FROM memories a JOIN memories b "
        "ON a.owner = b.owner AND a.id < b.id "
        "AND a.quarantined = b.quarantined "
        "WHERE a.owner = %s AND a.valid_to IS NULL AND b.valid_to IS NULL "
        "AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL "
        "AND 1 - (a.embedding <=> b.embedding) >= %s "
        "ORDER BY cos DESC LIMIT %s",
        (owner, DUP_COSINE, limit),
    )


async def _neighbors(db, owner, row_id, vec_literal, quarantined, k):
    return await db.fetch(
        "SELECT id, content, predicate, created_at, "
        "1 - (embedding <=> %s::vector) AS cos FROM memories "
        "WHERE owner = %s AND valid_to IS NULL AND id <> %s::uuid "
        "AND quarantined = %s AND embedding IS NOT NULL "
        "AND 1 - (embedding <=> %s::vector) >= %s "
        "ORDER BY embedding <=> %s::vector LIMIT %s",
        (vec_literal, owner, row_id, quarantined, vec_literal,
         CONTRA_NEIGHBOR, vec_literal, k),
    )


async def run_sweep(*, db, embedder, settings, owner: str,
                    row_cap: int = SWEEP_ROWS) -> dict:
    """Merge dup pairs, NLI-sweep contradictions. Returns the counts and
    ledgers an UPDATE_SWEEP event row (turn NULL: outside the dedup key)."""
    merged = retired_contra = checked = 0
    capped = False
    # Pass 1: near-dup merge (within trust partition).
    for p in await _dup_pairs(db, owner, PAIR_CAP):
        if merged + retired_contra >= MAX_RETIRE:
            capped = True
            break
        a, b = str(p["a"]), str(p["b"])
        keeper, dead = (a, b) if p["a_ts"] >= p["b_ts"] else (b, a)
        ok = await _retire(
            db, owner=owner, keeper_id=keeper, dead_id=dead,
            relation="duplicate",
            reason=f"updater merged near-dup pair (cos {p['cos']:.3f})",
        )
        if ok:
            merged += 1
    # Pass 2: contradiction sweep over recent live rows.
    rows = await db.fetch(
        "SELECT id, content, predicate, created_at, quarantined "
        "FROM memories WHERE owner = %s AND valid_to IS NULL "
        "AND embedding IS NOT NULL ORDER BY created_at DESC LIMIT %s",
        (owner, row_cap),
    )
    nli_down = False
    for r in rows:
        if checked >= PAIR_CAP or nli_down or capped:
            break
        vec, _ = await embedder.embed(r["content"])
        lit = pgvector_literal(vec)
        nbrs = await _neighbors(db, owner, str(r["id"]), lit,
                                r["quarantined"], NEIGHBOR_K)
        for n in nbrs:
            if checked >= PAIR_CAP or nli_down or capped:
                break
            if n["cos"] >= DUP_COSINE:
                continue  # pass 1 owned this pair
            if _is_speech_act(r["content"], r.get("predicate")) or \
                    _is_speech_act(n["content"], n.get("predicate")):
                continue  # speech acts are immutable history
            checked += 1
            older, newer = (
                (r, n) if r["created_at"] <= n["created_at"] else (n, r))
            try:
                fwd = await nli.verify(older["content"], newer["content"],
                                       settings)
                if fwd["p_contra"] < settings.nli_threshold:
                    continue
                rev = await nli.verify(newer["content"], older["content"],
                                       settings)
            except nli.NLIError as e:
                log.warning("updater NLI down (%s); stopping sweep", e)
                nli_down = True
                break
            if rev["p_contra"] < settings.nli_threshold:
                continue  # asymmetric: progression, not contradiction
            res = fwd
            if merged + retired_contra >= MAX_RETIRE:
                capped = True
                break
            ok = await _retire(
                db, owner=owner, keeper_id=str(newer["id"]),
                dead_id=str(older["id"]), relation="supersedes",
                reason=f"updater contra {res['p_contra']:.2f} newest-wins",
            )
            if ok:
                retired_contra += 1
    summary = {"merged": merged, "retired_contra": retired_contra,
               "pairs_checked": checked, "capped": capped}
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance, "
        "observer_verdict, scribe_action) VALUES (%s,'sweep',NULL,%s,%s,%s)",
        (owner, f"updater sweep: {merged} merged, "
                f"{retired_contra} contradictions retired, "
                f"{checked} pairs checked",
         Json({"keep": True, "reason": "updater sweep"}),
         Json({"op": "UPDATE_SWEEP", **summary})),
    )
    log.info("updater swept %s: %s", owner, summary)
    return summary


async def handle_job(*, db, embedder, settings, job) -> dict:
    """Queue adapter: UPDATE_SWEEP jobs carry {owner} in the payload."""
    return await run_sweep(
        db=db, embedder=embedder, settings=settings,
        owner=job.payload.get("owner", settings.owner),
    )

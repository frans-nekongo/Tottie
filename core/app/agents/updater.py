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
   path missed (G5 terse reversals). Numeric conflicts (same claim,
   swapped numbers) bypass NLI — it reads numbers as neutral — via
   the masked-cosine + subject-value rule (linker.numeric_candidate);
   differing numbers inside the subjects name variants (complement).
3. Numeric pass: pass 2's row window vindicates old rows by age, so
   the numeric rule ALSO scans all live pairs above NUMERIC_COS.
   NLI-free and embeds only numeric candidates.

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
from .cues import is_speech_act
from .linker import (NUMERIC_COS, NUMERIC_DELTA_MIN, NUMERIC_MASKED_COS,
                     is_opposition, mask_numbers, numeric_candidate)

log = logging.getLogger("tottie.updater")

# 0.98, not 0.95: parallel technical phrasing legitimately reaches
# 0.966 (live kill: Qwen-TTS-Tokenizer-12Hz vs 25Hz are DIFFERENT
# specs, merged as "dups"). Same evidence moved the eval line.
DUP_COSINE = 0.98
CONTRA_NEIGHBOR = 0.80
SWEEP_ROWS = 100
NEIGHBOR_K = 5
PAIR_CAP = 300
MAX_RETIRE = 15
# Speech-act guard lives in cues (shared with the write path's
# compare: requests are history on both lanes).


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


async def _numeric_pairs(db, owner, limit):
    return await db.fetch(
        "SELECT a.id AS a, b.id AS b, "
        "a.content AS a_content, b.content AS b_content, "
        "a.subject AS a_sub, b.subject AS b_sub, "
        "a.predicate AS a_pred, b.predicate AS b_pred, "
        "a.created_at AS a_ts, b.created_at AS b_ts, "
        "1 - (a.embedding <=> b.embedding) AS cos "
        "FROM memories a JOIN memories b "
        "ON a.owner = b.owner AND a.id < b.id "
        "AND a.quarantined = b.quarantined "
        "WHERE a.owner = %s AND a.valid_to IS NULL AND b.valid_to IS NULL "
        "AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL "
        "AND 1 - (a.embedding <=> b.embedding) >= %s "
        "ORDER BY cos DESC LIMIT %s",
        (owner, NUMERIC_COS, limit),
    )


async def _neighbors(db, owner, row_id, vec_literal, quarantined, k):
    return await db.fetch(
        'SELECT id, content, subject, predicate, "object", created_at, '
        "1 - (embedding <=> %s::vector) AS cos FROM memories "
        "WHERE owner = %s AND valid_to IS NULL AND id <> %s::uuid "
        "AND quarantined = %s AND embedding IS NOT NULL "
        "AND 1 - (embedding <=> %s::vector) >= %s "
        "ORDER BY embedding <=> %s::vector LIMIT %s",
        (vec_literal, owner, row_id, quarantined, vec_literal,
         CONTRA_NEIGHBOR, vec_literal, k),
    )


def _cos(a, b) -> float:
    import math
    return sum(x * y for x, y in zip(a, b)) / (
        math.sqrt(sum(x * x for x in a))
        * math.sqrt(sum(y * y for y in b)))


async def run_sweep(*, db, embedder, settings, owner: str,
                    row_cap: int = SWEEP_ROWS) -> dict:
    """Merge dup pairs, NLI-sweep contradictions. Returns the counts and
    ledgers an UPDATE_SWEEP event row (turn NULL: outside the dedup key)."""
    merged = retired_contra = checked = 0
    capped = False
    items: list = []
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
            items.append({"kind": "duplicate", "keeper": keeper,
                          "dead": dead, "cos": round(p["cos"], 4)})
    # Pass 2: contradiction sweep over recent live rows.
    rows = await db.fetch(
        'SELECT id, content, subject, predicate, "object", created_at, '
        "quarantined FROM memories WHERE owner = %s AND valid_to IS NULL "
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
            if is_speech_act(r["content"], r.get("predicate")) or \
                    is_speech_act(n["content"], n.get("predicate")):
                continue  # speech acts are immutable history
            checked += 1
            older, newer = (
                (r, n) if r["created_at"] <= n["created_at"] else (n, r))
            # Numeric conflicts bypass NLI: it reads swapped numbers as
            # neutral, so the deadline 2025/2026 pair coexisted forever.
            # Same claim shape (masked-cos) + swapped values + numbers
            # outside the subjects (variant names like 12Hz/25Hz mean
            # complement, never conflict).
            numeric_mcos = None
            if n["cos"] >= NUMERIC_COS and numeric_candidate(
                    r["content"], n["content"],
                    r.get("subject"), n.get("subject")):
                mvec_r, _ = await embedder.embed(
                    mask_numbers(r["content"]))
                mvec_n, _ = await embedder.embed(
                    mask_numbers(n["content"]))
                mcos = _cos(mvec_r, mvec_n)
                if mcos >= NUMERIC_MASKED_COS and \
                        mcos - n["cos"] >= NUMERIC_DELTA_MIN:
                    numeric_mcos = mcos
            if numeric_mcos is None:
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
                # Polarity-only opposition gate (linker.is_opposition):
                # NLI alone misfires ~1.00 on boilerplate and facets.
                if not is_opposition(older["content"], newer["content"],
                                     n["cos"], older.get("object"),
                                     newer.get("object")):
                    continue
                res = fwd
            else:
                res = None
            if merged + retired_contra >= MAX_RETIRE:
                capped = True
                break
            if res is None:
                reason = ("updater numeric-conflict "
                          f"{numeric_mcos:.2f} newest-wins")
            else:
                reason = (f"updater contra {res['p_contra']:.2f} "
                          "newest-wins")
            ok = await _retire(
                db, owner=owner, keeper_id=str(newer["id"]),
                dead_id=str(older["id"]), relation="supersedes",
                reason=reason,
            )
            if ok:
                retired_contra += 1
                item = {"kind": "contra",
                        "keeper": str(newer["id"]),
                        "dead": str(older["id"])}
                if res is None:
                    item["masked_cos"] = round(numeric_mcos, 3)
                    item["via"] = "numeric"
                else:
                    item["p_contra"] = round(res["p_contra"], 3)
                items.append(item)
    # Pass 3: numeric conflicts over ALL live rows, not just the recent
    # window. Pass 2's row_cap vindicates old rows by age: the deadline
    # 2025/2026 pair sat at rank ~672, never examined, serving both
    # years to recall forever. This pass is NLI-free (numbers read
    # neutral anyway) and embeds only numeric candidates, so scanning
    # the full pair list is cheap. Same cap, same ledger.
    for p in await _numeric_pairs(db, owner, PAIR_CAP):
        if checked >= PAIR_CAP or capped:
            break
        if p["cos"] >= DUP_COSINE:
            continue  # pass 1 owned this pair
        a_id, b_id = str(p["a"]), str(p["b"])
        if is_speech_act(p["a_content"], p["a_pred"]) or \
                is_speech_act(p["b_content"], p["b_pred"]):
            continue  # speech acts are immutable history
        if not numeric_candidate(p["a_content"], p["b_content"],
                                 p["a_sub"], p["b_sub"]):
            continue
        checked += 1
        mvec_a, _ = await embedder.embed(mask_numbers(p["a_content"]))
        mvec_b, _ = await embedder.embed(mask_numbers(p["b_content"]))
        mcos = _cos(mvec_a, mvec_b)
        if mcos < NUMERIC_MASKED_COS or \
                mcos - p["cos"] < NUMERIC_DELTA_MIN:
            continue
        if merged + retired_contra >= MAX_RETIRE:
            capped = True
            break
        older_id, newer_id = (a_id, b_id) if p["a_ts"] <= p["b_ts"] \
            else (b_id, a_id)
        ok = await _retire(
            db, owner=owner, keeper_id=newer_id, dead_id=older_id,
            relation="supersedes",
            reason=f"updater numeric-conflict {mcos:.2f} newest-wins",
        )
        if ok:
            retired_contra += 1
            items.append({"kind": "contra", "keeper": newer_id,
                          "dead": older_id, "masked_cos": round(mcos, 3),
                          "via": "numeric"})
    summary = {"merged": merged, "retired_contra": retired_contra,
               "pairs_checked": checked, "capped": capped,
               "items": items}
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

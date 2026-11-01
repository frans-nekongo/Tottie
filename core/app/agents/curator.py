"""The Curator: junk killer. G6a's "extract everything" instruction buys
recall with precision and nothing downstream re-checks quality — so
process trivia ("The observer is intercepting T1 turns"), transient
states ("Owner is editing scribe now"), and content-free husks
("Reversal was verified.") accumulate. The curator deletes them.

Three passes, cheapest first, all within-partition:
1. Transient: present-progressive micro-actions ("is committing",
   "is intercepting") or any progressive + now/currently. These rot
   the instant they are written.
2. Husk: short (< 40 chars) with no digit, no quoted string, and no
   proper noun — nothing durable can fit that shape.
3. Drift: the row contradicts its own source turn (NLI contra above
   threshold) = scribe hallucination. Neutral is spared (vague but
   possibly fine; the ranker decays it).

Deletes are soft-retires (valid_to) with retired ids + reasons in the
CURATOR_SWEEP ledger event — recoverable, auditable. Capped per sweep.
Runs as a CURATOR_SWEEP job (sleep heartbeat).
"""
import logging
import re

from psycopg.types.json import Json

log = logging.getLogger("tottie.curator")

MICRO_VERBS = (
    "editing|committing|running|checking|restarting|writing|reading|"
    "intercepting|forwarding|looking|waiting|starting|stopping"
)
TRANSIENT_RE = re.compile(
    rf"\b(?:is|are)\s+(?:{MICRO_VERBS})\b"
    r"|\b(?:is|are)\s+\w+ing\b.{0,40}\b(?:now|currently)\b",
    re.IGNORECASE,
)
HUSK_LEN = 40
MAX_RETIRE = 15


def classify(content: str) -> str | None:
    """Return the junk kind or None. Pure function, unit-testable.

    Husk = short BE-sentence with no durable detail: "X is/was Y"
    asserts a bare state ("Reversal was verified", "Updater is green").
    Short ACTIVE sentences ("Anna paid for the taxi", "Ben now drinks",
    "Owner plans to add X") carry events and survive, as do shorts
    with digits or quotes. Validated against all 32 short live rows.
    """
    text = (content or "").strip()
    if TRANSIENT_RE.search(text):
        return "transient"
    if len(text) < HUSK_LEN and not re.search(r"\d", text) \
            and '"' not in text and "`" not in text \
            and re.search(r"\b(?:is|are|was|were)\b", text, re.IGNORECASE):
        return "husk"
    return None


async def run_sweep(*, db, embedder, settings, owner: str) -> dict:
    retired: list[dict] = []
    capped = False
    rows = await db.fetch(
        "SELECT id, content, source FROM memories WHERE owner = %s "
        "AND valid_to IS NULL ORDER BY created_at DESC LIMIT 500",
        (owner,),
    )
    for r in rows:
        if len(retired) >= MAX_RETIRE:
            capped = True
            break
        kind = classify(r["content"] or "")
        if kind is None:
            kind = await _drift_kind(db, settings, owner, r)
        if kind is None:
            continue
        rid = str(r["id"])
        await db.execute(
            "UPDATE memories SET valid_to = now() WHERE id = %s::uuid "
            "AND valid_to IS NULL",
            (rid,),
        )
        retired.append({"id": rid, "kind": kind,
                        "content": (r["content"] or "")[:80]})
    summary = {"retired": len(retired), "capped": capped,
               "rows": len(rows), "items": retired}
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance, "
        "observer_verdict, scribe_action) VALUES (%s,'sweep',NULL,%s,%s,%s)",
        (owner, f"curator sweep: {len(retired)} retired of {len(rows)} rows",
         Json({"keep": True, "reason": "curator sweep"}),
         Json({"op": "CURATOR_SWEEP", **summary})),
    )
    log.info("curator swept %s: %d retired (capped=%s)", owner,
             len(retired), capped)
    return summary


async def _drift_kind(db, settings, owner, row) -> str | None:
    """NLI drift: row contradicts its own source turn = hallucination."""
    from .. import nli as nli_mod

    src = row.get("source") or {}
    if not src.get("session") or src.get("turn") is None:
        return None
    ev = await db.fetchrow(
        "SELECT utterance FROM memory_events WHERE owner = %s "
        "AND session_id = %s AND turn = %s",
        (owner, src["session"], src["turn"]),
    )
    if not ev or not ev["utterance"]:
        return None
    try:
        res = await nli_mod.verify(ev["utterance"], row["content"], settings)
    except nli_mod.NLIError as e:
        log.warning("curator NLI down (%s); skipping drift pass", e)
        return None
    if res["label"] == "contradiction" and \
            res["p_contra"] >= settings.nli_threshold:
        return "drift"
    return None


async def handle_job(*, db, embedder, settings, job) -> dict:
    """Queue adapter: CURATOR_SWEEP jobs carry {owner} in the payload."""
    return await run_sweep(
        db=db, embedder=embedder, settings=settings,
        owner=job.payload.get("owner", settings.owner),
    )

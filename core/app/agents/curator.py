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
3. Drift: DISABLED (DRIFT_ENABLED=False). Three verifiers were
   stacked and all massacred true rows at 0 confirmed catches; the
   right layer is extraction atomicity (U3 splitter). Code kept for
   the revival; tests pin the disabled contract meanwhile.

Deletes are soft-retires (valid_to) with retired ids + reasons in the
CURATOR_SWEEP ledger event — recoverable, auditable. Capped per sweep.
Runs as a CURATOR_SWEEP job (sleep heartbeat).
"""
import logging
import math
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
# Drift verification embeds ~60 sentences per row: newest 100 only.
DRIFT_ROWS = 100
# Drift is DISABLED: three verifiers stacked (whole-turn NLI, clause
# cosine, clause + pair-windows) and every one massacred true rows —
# NLI inverts on long premises, and scribe compresses whole SECTIONS
# into one row so no local window verifies (30 false retires, 0
# confirmed hallucinations caught). The right layer is extraction
# atomicity (U3 splitter): atomic rows verify trivially. Re-enable
# drift WITH the splitter, never before. Transient + husk stay live.
DRIFT_ENABLED = False


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
    for n, r in enumerate(rows):
        if len(retired) >= MAX_RETIRE:
            capped = True
            break
        kind = classify(r["content"] or "")
        if kind is None and n < DRIFT_ROWS:
            kind = await _drift_kind(db, embedder, settings, owner, r)
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


async def _drift_kind(db, embedder, settings, owner, row) -> str | None:
    """Drift = row unsupported by its own source turn (hallucination).

    Measured method (Nov 2026, 5 supported vs 5 unrelated pairs): the
    DISABLED (see DRIFT_ENABLED): kept for the U3-splitter revival.
    History: whole-turn NLI cross-encoder INVERTS on long premises —
    entailed rows read
    contradiction 0.95-0.99 against their own 2k-char turn, while the
    same row against one sentence reads entailment 0.994. So support is
    sentence-cosine first (supported rows hit 0.78-0.95 on their best
    sentence, unrelated pairs 0.64-0.70), with an NLI backstop on the
    top sentence for paraphrase in the gray zone; inversions (high
    cosine, opposite meaning) are caught by symmetric NLI-contra on
    the top sentence, which is short — the regime where the NLI works
    (proven: entailment 0.994 on one sentence vs contradiction 0.988
    on the full 2k turn). DRIFT iff unsupported (best_cos < 0.70 AND
    entail < 0.5) OR inverted (symmetric contra >= 0.80 on a close
    pair); else keep. Verification is per substantial clause
    (>= 30 chars), not per row: scribe merges 2-4 sentences per row
    and no single sentence reaches 0.70 against a merge (proven by
    3 more false retires on the row-level version).
    """
    from .. import nli as nli_mod  # noqa: F401 - kept for revival

    if not DRIFT_ENABLED:
        return None
    src = row.get("source") or {}
    if not src.get("session"):
        return None
    turns = list(dict.fromkeys(src.get("turns") or
                               ([src["turn"]] if src.get("turn") is not None
                                else [])))
    if not turns:
        return None
    sents: list[str] = []
    for t in turns:
        ev = await db.fetchrow(
            "SELECT utterance FROM memory_events WHERE owner = %s "
            "AND session_id = %s AND turn = %s",
            (owner, src["session"], t),
        )
        if not ev or not ev["utterance"]:
            continue
        sents += [s.strip() for s in
                  re.split(r"(?<=[.!?])\s+|\n+", ev["utterance"])
                  if len(s.strip()) > 25][:40]
    sents = sents[:60]
    if not sents:
        return None
    # Verify each claim, not the bundle: scribe merges 2-4 sentences
    # per row, and no single sentence reaches 0.70 against a merge.
    clauses = _clauses(row["content"] or "")
    if not clauses:
        return None
    try:
        # Singles + adjacent pairs: scribe claims routinely span two
        # source sentences ("never rebuild all" + "the command is X"),
        # and no single sentence reaches 0.70 against such a span.
        windows = list(sents)
        windows += [sents[i] + " " + sents[i + 1]
                    for i in range(len(sents) - 1)]
        sent_vecs = []
        for st in windows:
            vec, _ = await embedder.embed(st)
            sent_vecs.append(vec)
        sents = windows
        for clause in clauses:
            if not await _clause_supported(
                    embedder, nli_mod, settings, sent_vecs, sents,
                    clause):
                return "drift"
        return None
    except nli_mod.NLIError as e:
        log.warning("curator verifier down (%s); skipping drift pass", e)
        return None


def _clauses(content: str) -> list[str]:
    """Substantial clauses: split sentences, then sub-split on
    commas/ands. Merges join sentences with newlines, so sentence
    boundaries split first (a two-sentence merge is two claims).
    Fragments < 30 chars carry into the previous clause — dropping
    them silently unverifies real meaning ("never rebuild all")."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", content):
        for c in re.split(r"\s*(?:;|, and|,| and )\s+", sent):
            c = c.strip()
            if not c:
                continue
            if len(c) < 30 and out:
                out[-1] = out[-1] + ", " + c
            elif len(c) >= 30:
                out.append(c)
            elif out:
                out[-1] = out[-1] + ", " + c
            else:
                out.append(c)
    return [c for c in out if len(c) >= 30]


async def _clause_supported(embedder, nli_mod, settings, sent_vecs,
                            sents, clause) -> bool:
    """One clause is supported iff its best sentence reaches 0.70 or
    NLI-entails it (>= 0.5); an inversion (symmetric contra >= 0.80
    on a close pair) convicts even a high-cosine clause."""
    clause_vec, _ = await embedder.embed(clause)
    scored = sorted(((_cos(clause_vec, v), st)
                     for v, st in zip(sent_vecs, sents)),
                    key=lambda t: -t[0])
    best, top = scored[0]
    res = await nli_mod.verify(top, clause, settings)
    if res["p_entail"] >= 0.5:
        return True
    if best >= 0.70:
        back = await nli_mod.verify(clause, top, settings)
        return not (res["p_contra"] >= 0.80
                    and back["p_contra"] >= 0.80)
    return False


def _cos(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


async def handle_job(*, db, embedder, settings, job) -> dict:
    """Queue adapter: CURATOR_SWEEP jobs carry {owner} in the payload."""
    return await run_sweep(
        db=db, embedder=embedder, settings=settings,
        owner=job.payload.get("owner", settings.owner),
    )

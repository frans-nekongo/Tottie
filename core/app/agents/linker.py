"""The Linker: entity links + typed edges. Zero LLM calls: entities come
from the scribe's own subject/object fields (71% of live rows carry them;
the scribe already did the hard NLP of naming doer and doing).

Per row: other live rows sharing a normalized subject or object get an
`entity` edge (weight 0.7, capped per row). Shared-entity pairs then go
through the NLI verifier for typing: entailment either way -> `supports`
(1.0); symmetric contradiction -> `contradicts` (0.3: opposed but
associated, so the story can narrate the tension); neutral stays a
plain entity edge. Ultra-common subjects (owner/user/system) never
link: they would fan out to everything (cue overload).

Runs as a sweep over recent link-less rows (sleep heartbeat) or as a
single-row LINK_ROW job. Within-partition only, like the updater.
"""
import logging
import re

from ..db import pgvector_literal
from . import reconcile

log = logging.getLogger("tottie.linker")

STOP_ENTITIES = {"owner", "user", "system", "it", "they", "we", "you"}
LINKS_PER_ROW = 10
SWEEP_ROWS = 50
W_ENTITY = 0.7
W_SUPPORTS = 1.0
W_CONTRA = 0.3
# Typed relations need topical overlap: the NLI reads far-apart pairs as
# contradiction ~1.00 (int8 quirk), so supports/contradicts below 0.80
# would be quirk artifacts, not judgments. Far pairs stay plain entity.
TYPED_COSINE = 0.80


def _norm(value):
    if value is None:
        return None
    v = " ".join(value.split()).lower()
    return v or None


def _entities(row):
    # Compound subjects name several entities ("NKNGO-LANG and
    # translate"): split them or bridge rows never link (live case:
    # the school<->company bridge row sat edge-less).
    out = []
    for v in (row.get("subject"), row.get("object")):
        if v is None:
            continue
        for part in re.split(r"\s+and\s+|,\s*|/\s*|\s+&\s+", v):
            n = _norm(part)
            if n and n not in STOP_ENTITIES and n not in out:
                out.append(n)
    return out


async def _candidates(db, owner, row_id, vec_literal, quarantined, entities):
    if not entities:
        return []
    return await db.fetch(
        "SELECT id, content, 1 - (embedding <=> %s::vector) AS cos "
        "FROM memories WHERE owner = %s "
        "AND valid_to IS NULL AND id <> %s::uuid AND quarantined = %s "
        "AND (lower(btrim(subject)) = ANY(%s) "
        "OR lower(btrim(\"object\")) = ANY(%s)) "
        "ORDER BY created_at DESC LIMIT %s",
        (vec_literal, owner, row_id, quarantined, entities, entities,
         LINKS_PER_ROW),
    )


async def _already_linked(db, owner, src, dst):
    return await db.fetchval(
        "SELECT 1 FROM memory_links WHERE owner = %s AND src = %s::uuid "
        "AND dst = %s::uuid AND relation IN "
        "('entity', 'supports', 'contradicts')",
        (owner, src, dst),
    )


_TYPE_STOPS = frozenset(
    "the and for with from that this these those then than them they you "
    "your are was were has have had not but our its into over after "
    "such only also when where which who whom whose why how does did "
    "done just".split()
)


_NEGATIONS = frozenset(
    "not never no none neither nor without cannot can't won't don't "
    "doesn't didn't isn't aren't wasn't weren't hasn't haven't hadn't "
    "couldn't shouldn't wouldn't".split()
)


def _words(t):
    return {w for w in re.findall(r"[a-z0-9']+", t.lower())
            if len(w) > 3 and w not in _TYPE_STOPS}


def _negation_asymmetry(a_content, b_content) -> bool:
    def neg(t):
        toks = set(re.findall(r"[a-z']+", t.lower()))
        return bool(toks & _NEGATIONS)
    return neg(a_content) != neg(b_content)


def _shared_words(a_content, b_content) -> int:
    return len(_words(a_content) & _words(b_content))


def is_opposition(a_content, b_content, cos: float) -> bool:
    """One shared opposition rule (linker typing + updater sweep):
    symmetric-NLI-contra misfires on same-subject facets AND on
    parallel technical phrasing, so NLI alone never convicts.
    Opposition needs a polarity flip, or a shared topic (4+ words)
    at modest cosine — near-identical phrasing (cos >= 0.90) with
    differing specs is complement, not clash (live: Qwen 12Hz vs
    25Hz tokenizers at 0.966). Known gap: paraphrase reversals with
    no negation and few shared words ("I eat meat" -> "I'm
    vegetarian") pass; the write path (reconcile correction lane)
    catches live ones, the sweep cannot tell them from facets."""
    if _negation_asymmetry(a_content, b_content):
        return True
    return _shared_words(a_content, b_content) >= 4 and cos < 0.90


async def _type_pair(nli_mod, settings, a_content, b_content, cos):
    """NLI edge typing: supports / contradicts / entity (neutral or far)."""
    if cos < TYPED_COSINE:
        return "entity", W_ENTITY, cos
    fwd = await nli_mod.verify(a_content, b_content, settings)
    if fwd["label"] == "entailment" and \
            fwd["p_entail"] >= settings.nli_threshold:
        return "supports", W_SUPPORTS, fwd["p_entail"]
    if fwd["label"] == "contradiction" and \
            fwd["p_contra"] >= settings.nli_threshold:
        rev = await nli_mod.verify(b_content, a_content, settings)
        if rev["label"] == "contradiction" and \
                rev["p_contra"] >= settings.nli_threshold:
            # Shared opposition rule: NLI alone misfires (14 false
            # edges on code-trace rows at 0.97-1.00; scores can't
            # separate them from real opposition).
            if is_opposition(a_content, b_content, cos):
                return "contradicts", W_CONTRA, fwd["p_contra"]
        return "entity", W_ENTITY, fwd["p_contra"]
    rev = await nli_mod.verify(b_content, a_content, settings)
    if rev["label"] == "entailment" and \
            rev["p_entail"] >= settings.nli_threshold:
        return "supports", W_SUPPORTS, rev["p_entail"]
    return "entity", W_ENTITY, max(fwd["p_contra"], rev["p_contra"])


async def link_row(*, db, embedder, settings, memory_id: str) -> dict:
    """Link one row to its entity-sharers. Returns counts."""
    from .. import nli as nli_mod

    row = await db.fetchrow(
        "SELECT id, owner, content, subject, \"object\", quarantined "
        "FROM memories WHERE id = %s::uuid AND valid_to IS NULL",
        (memory_id,),
    )
    if row is None:
        return {"linked": 0, "typed": {}}
    owner = row["owner"]
    ents = _entities(row)
    typed: dict[str, int] = {}
    linked = 0
    vec, _ = await embedder.embed(row["content"])
    lit = pgvector_literal(vec)
    for cand in await _candidates(db, owner, str(row["id"]), lit,
                                  row["quarantined"], ents):
        if await _already_linked(db, owner, str(row["id"]), str(cand["id"])):
            continue
        try:
            rel, weight, score = await _type_pair(
                nli_mod, settings, row["content"], cand["content"],
                float(cand["cos"]))
        except nli_mod.NLIError as e:
            log.warning("linker NLI down (%s); stopping row", e)
            break
        async with db.transaction() as conn:
            await reconcile._link(
                conn, owner=owner, src=str(row["id"]),
                dst=str(cand["id"]), relation=rel, weight=weight,
                reason=f"linker shared-entity {rel} ({score:.2f})",
            )
        linked += 1
        typed[rel] = typed.get(rel, 0) + 1
    return {"linked": linked, "typed": typed}


async def run_sweep(*, db, embedder, settings, owner: str,
                    row_cap: int = SWEEP_ROWS) -> dict:
    """Link recent rows that have no entity-family edges yet."""
    rows = await db.fetch(
        "SELECT m.id FROM memories m WHERE m.owner = %s "
        "AND m.valid_to IS NULL AND m.subject IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM memory_links l "
        "WHERE l.owner = m.owner AND l.src = m.id AND l.relation IN "
        "('entity', 'supports', 'contradicts')) "
        "ORDER BY m.created_at DESC LIMIT %s",
        (owner, row_cap),
    )
    total = {"rows": 0, "linked": 0, "typed": {}}
    for r in rows:
        out = await link_row(db=db, embedder=embedder, settings=settings,
                             memory_id=str(r["id"]))
        total["rows"] += 1
        total["linked"] += out["linked"]
        for k, v in out["typed"].items():
            total["typed"][k] = total["typed"].get(k, 0) + v
    log.info("linker swept %s: %s", owner, total)
    return total


async def handle_job(*, db, embedder, settings, job) -> dict:
    """Queue adapter: LINK_ROW jobs carry {memory_id} or {owner}."""
    if job.payload.get("memory_id"):
        return await link_row(db=db, embedder=embedder, settings=settings,
                              memory_id=job.payload["memory_id"])
    return await run_sweep(db=db, embedder=embedder, settings=settings,
                           owner=job.payload.get("owner", settings.owner))

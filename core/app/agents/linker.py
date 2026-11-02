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
        'SELECT id, content, subject, "object", '
        "1 - (embedding <=> %s::vector) AS cos "
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


_NEGATIONS = frozenset(
    "not never no none neither nor without cannot can't won't don't "
    "doesn't didn't isn't aren't wasn't weren't hasn't haven't hadn't "
    "couldn't shouldn't wouldn't".split()
)


def _negation_asymmetry(a_content, b_content) -> bool:
    def neg(t):
        toks = set(re.findall(r"[a-z']+", t.lower()))
        return bool(toks & _NEGATIONS)
    return neg(a_content) != neg(b_content)


_WORD_RE = re.compile(r"[a-z0-9]+")
_EXT_RE = re.compile(r"\.[a-z0-9]+$")


def _same_subject(a_subject: str | None, b_subject: str | None) -> bool:
    """Entity match for the polarity gate. A reversal is one entity's
    one slot flipping — a feature fact (subject retrieve.py) and its
    test (subject test_concept_boost_promotes_only_matches) are
    different facts even when their objects nest ("concept boost" in
    "concept boost leg") and the NLI misfires 1.00. Word overlap over
    content words: file extensions stripped first (sibling scribes
    write "mcp_client" and "mcp_client.py" for one entity — "py" must
    not bridge retrieve.py to mcp_client.py), stopwords excluded.
    Either side NULL or content-empty (pronouns like "it") falls
    through to True: uninformative subjects can't prove difference,
    so object+polarity decide as before. Veto-only: disjoint
    informative subjects silence the gate, never fire it."""
    from .cues import STOPWORDS
    if a_subject is None or b_subject is None:
        return True
    a_norm, b_norm = _norm(a_subject), _norm(b_subject)
    if a_norm is None or b_norm is None:
        return True
    a_words = {w for w in _WORD_RE.findall(_EXT_RE.sub("", a_norm))
               if w not in STOPWORDS}
    b_words = {w for w in _WORD_RE.findall(_EXT_RE.sub("", b_norm))
               if w not in STOPWORDS}
    if not a_words or not b_words:
        return True
    return bool(a_words & b_words)


def _same_object(a_object: str | None, b_object: str | None) -> bool:
    """Same-slot test for the polarity gate. Exact string equality
    vetoed true reversals whose scribe elaborated the object (live:
    "4000 chars" vs "output at 4000 chars" with NLI 0.998/0.986 both
    ways — the truncation twin the sweep could not kill). Token
    overlap over content words: half or more of the shorter object's
    words shared means one slot. Stopwords excluded, or "the code" vs
    "the gate" would convict on "the". Either side empty after
    filtering falls back to exact equality (single-word slots like
    "alcohol" keep today's behavior). String containment was tried
    and dropped: it missed the true stale-row kill ("output to 4000
    chars" vs "output at 4000 chars" differ by one preposition).
    Overlap's own false-fire (nested "concept boost" in "concept
    boost leg" convicting a feature for its test) is vetoed one layer
    up by _same_subject, not here."""
    from .cues import STOPWORDS
    if a_object is None or b_object is None:
        return True
    a_norm, b_norm = _norm(a_object), _norm(b_object)
    if a_norm is None or b_norm is None:
        return a_norm == b_norm
    a_words = {w for w in _WORD_RE.findall(a_norm) if w not in STOPWORDS}
    b_words = {w for w in _WORD_RE.findall(b_norm) if w not in STOPWORDS}
    if not a_words or not b_words:
        return a_norm == b_norm
    return len(a_words & b_words) / min(len(a_words), len(b_words)) >= 0.5


def is_opposition(a_content, b_content, cos: float,
                  a_object: str | None = None,
                  b_object: str | None = None,
                  a_subject: str | None = None,
                  b_subject: str | None = None) -> bool:
    """Polarity-only opposition gate (linker typing + updater sweep):
    symmetric-NLI-contra misfires ~1.00 on boilerplate and facets, so
    NLI alone never convicts. The old shared-words clause (4+ words,
    cos < 0.90) fired on template boilerplate and murdered siblings
    (POST /agents/pair retired /heartbeat at NLI 0.99) while sleeping
    on true near-identical conflicts (deadline 2025 vs 2026 at 0.88:
    high-cos was excluded). Shared boilerplate is not aboutness.
    Polarity needs the SAME object: a flip about one slot (Ben drinks
    vs does-not, both "alcohol") is a reversal; a "never" in one test
    description vs another test's expectation is noise about different
    slots (live: test_linker never-links retired reverse-entailment).
    NULL objects can't differ, so NULL pairs fall through to polarity
    alone. Numeric conflicts (same claim, swapped numbers) bypass NLI —
    it reads numbers as neutral — and are judged by numeric_candidate
    in the updater, never here. Known gap: paraphrase reversals with
    no negation ("I eat meat" -> "I'm vegetarian") pass the sweep; the
    write path (similarity-gated SUPERSEDE) catches live ones."""
    if not _negation_asymmetry(a_content, b_content):
        return False
    if not _same_subject(a_subject, b_subject):
        return False
    return _same_object(a_object, b_object)


_NUMBER_RE = re.compile(r"\d[\d,.]*")
# Numeric-conflict gates (updater only): same claim shape with swapped
# numbers. Measured (bge-small): deadline 2025/2026 masked 0.9013, 3
# differing numbers FIRES; Qwen 12Hz/25Hz variants masked 0.8906 must
# NOT (differing numbers live in the subjects — variant names, not
# values); same-variant Qwen spec sheets masked 0.908 with 6+
# differing numbers must NOT (different measurements = different
# facts, not one swapped slot).
NUMERIC_COS = 0.85  # cheap raw-cos prefilter before embedding masked text
NUMERIC_MASKED_COS = 0.895
NUMERIC_SYMDIFF_MAX = 3  # one swapped slot, not two spec sheets
# Masking must IMPROVE similarity: the numbers must constitute the
# difference. Deadline 2025/2026: masked-raw = +0.020 (the year IS the
# claim). Test descriptions sharing a template with incidental weights
# (1.0 vs 0.7): +0.012/-0.007 (the test name differs, weights don't
# matter) — masking barely moves them, so they stay silent.
NUMERIC_DELTA_MIN = 0.015


def _numbers(text: str) -> set[str]:
    return {m.group(0).rstrip(".") for m in _NUMBER_RE.finditer(text or "")}


def _subject_numbers(subject: str | None) -> set[str]:
    return _numbers(subject)


def numbers_differ(a_content: str, b_content: str) -> bool:
    """Both-ways number difference: each side has a number the other
    lacks. One-way difference is elaboration ("fee N$360" vs "fee N$360,
    account 555"), not conflict."""
    na, nb = _numbers(a_content), _numbers(b_content)
    return bool(na - nb) and bool(nb - na)


def numbers_in_subject(symdiff: set[str], *subjects: str | None) -> bool:
    """True when a differing number names WHICH thing (subject) rather
    than filling the slot (value): Qwen 12Hz vs 25Hz differ in the
    variant name — complement. Deadline 2025 vs 2026 differ only in
    values with number-free subjects — conflict."""
    subj_nums: set[str] = set()
    for s in subjects:
        subj_nums |= _subject_numbers(s)
    return bool(symdiff & subj_nums)


def mask_numbers(text: str) -> str:
    return _NUMBER_RE.sub("#", text or "")


def numeric_candidate(a_content: str, b_content: str,
                      a_subject: str | None,
                      b_subject: str | None) -> bool:
    """Sync precheck: numbers swapped both ways, few enough to be one
    slot (not two spec sheets), AND every differing number lives
    outside the subjects (values, not variant names). The caller
    confirms with masked-cosine >= NUMERIC_MASKED_COS."""
    if not numbers_differ(a_content, b_content):
        return False
    na, nb = _numbers(a_content), _numbers(b_content)
    symdiff = (na - nb) | (nb - na)
    if len(symdiff) > NUMERIC_SYMDIFF_MAX:
        return False
    return not numbers_in_subject(symdiff, a_subject, b_subject)


async def _type_pair(nli_mod, settings, a_content, b_content, cos,
                   a_object=None, b_object=None,
                   a_subject=None, b_subject=None):
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
            if is_opposition(a_content, b_content, cos, a_object,
                             b_object, a_subject, b_subject):
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
                float(cand["cos"]), row.get("object"),
                cand.get("object"), row.get("subject"),
                cand.get("subject"))
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

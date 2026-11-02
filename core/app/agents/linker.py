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


def _subject_words(subject: str | None) -> set[str]:
    """Content words of a subject: extension-stripped, stopwords out.
    Empty set = uninformative (NULL, blank, or pronouns like "it")."""
    from .cues import STOPWORDS
    norm = _norm(subject)
    if norm is None:
        return set()
    return {w for w in _WORD_RE.findall(_EXT_RE.sub("", norm))
            if w not in STOPWORDS}


def _content_words(content: str) -> set[str]:
    from .cues import STOPWORDS
    return {w for w in _WORD_RE.findall(content.lower())
            if w not in STOPWORDS}


def _object_words(obj: str | None) -> set[str]:
    """Content-word set of a triple object (None-safe). Powers both the
    coverage test and the exact-slot test for predicate flips."""
    from .cues import STOPWORDS
    norm = _norm(obj)
    if norm is None:
        return set()
    return {w for w in _WORD_RE.findall(norm) if w not in STOPWORDS}


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
    a_words = _subject_words(a_subject)
    b_words = _subject_words(b_subject)
    if not a_words or not b_words:
        return True
    return bool(a_words & b_words)


_CORRECTION_PREFIX_RE = re.compile(r"^\s*correction\s*:\s*")
_NUMBER_RUN_RE = re.compile(r"\d+")


def _masked_shape(content: str) -> str:
    """Content modulo values: lowercased, "Correction:" prefix off,
    every number run collapsed to N, whitespace squeezed. Two turns
    with the same shape claim the same slot with swapped values."""
    s = _CORRECTION_PREFIX_RE.sub("", content.lower())
    s = _NUMBER_RUN_RE.sub("N", s)
    return " ".join(s.split())


# Plain tokens (no possessives): "Bex's" must yield identity "bex" to
# match the lowercased content-word sets it is compared against.
_IDENTITY_RE = re.compile(r"[A-Za-z0-9]+")


def _identity_words(raw_subject: str | None) -> set[str]:
    """Proper-name words in a RAW (unnormalized) subject: capitalized
    tokens minus stopwords. "Bex's locker" names Bex; "deadline" and
    "safe" name no one. Case is the signal — callers must pass the
    raw subject, never the normalized form."""
    from .cues import STOPWORDS
    if not raw_subject:
        return set()
    return {w.lower() for w in _IDENTITY_RE.findall(raw_subject)
            if w[:1].isupper() and w.lower() not in STOPWORDS}


# High-cosine link bar (pairs the F2a bypass floor): at cos >= 0.70 the
# embedding itself is entity evidence — "deadline moved to Wednesday"
# paraphrases "rebrand due Friday" (0.81) while bystander noise sits
# near 0.3-0.5. Only consulted when a subject is missing; informative
# subjects decide by words, never by cosine.
LINK_COS_FLOOR = 0.70


def entity_linked(old_subject: str | None, new_subject: str | None,
                  old_content: str, new_content: str,
                  mcos: float | None = None) -> bool:
    """WHICH-slot evidence for the write path. A correction marker says
    THAT ("this is a correction"); only entity evidence says WHICH row
    it corrects. Live murders: "Correction: the safe code changed to
    9177" killed subject-less "Library fines were waived", and "Bex's
    locker ..." killed Tuli's via the shared template word "locker".
    Link iff one side's FULL subject word-set is covered by the other
    side's subject+content words: naming the whole entity is WHICH
    evidence; a single shared template word is not. Scribe wording
    varies ("namib roasters rebrand" vs "deadline" name one entity —
    G4), but a true correction talks ABOUT the old entity. Either
    subject uninformative: no entity to cover, so the contents must
    carry the evidence — identical modulo values (masked shape),
    two-plus shared content words ("review meeting" links D6; a lone
    template word never does), or high cosine (the paraphrase knows
    "deadline moved" means the rebrand's due date even with zero
    shared words)."""
    a_words = _subject_words(old_subject)
    b_words = _subject_words(new_subject)
    if not a_words or not b_words:
        if _masked_shape(old_content) == _masked_shape(new_content):
            return True
        if len(_content_words(old_content)
               & _content_words(new_content)) >= 2:
            return True
        return mcos is not None and mcos >= LINK_COS_FLOOR
    if a_words <= (b_words | _content_words(new_content)):
        return True
    return b_words <= (a_words | _content_words(old_content))


def _same_object(a_object: str | None, b_object: str | None) -> bool:
    """Same-slot test for the polarity gate. Exact string equality
    vetoed true reversals whose scribe elaborated the object (live:
    "4000 chars" vs "output at 4000 chars" with NLI 0.998/0.986 both
    ways — the truncation twin the sweep could not kill). Token
    overlap over content words: the SHORTER side fully covered means
    one slot (elaboration adds words around the value, never swaps
    them). Stopwords excluded, or "the code" vs "the gate" would
    convict on "the". Either side empty after filtering falls back to
    exact equality (single-word slots like "alcohol" keep today's
    behavior). A 0.5 threshold was tried and dropped: it convicted
    journey stops sharing only a generic noun ("parcel to Berlin" vs
    "parcel to Marta" share "parcel" — different slots, twinned).
    Every true kill on record covers 1.0; partial overlap is always a
    different slot. Nested technical facets ("concept boost" in
    "concept boost leg") still fire here and are vetoed one layer up
    by the subject/entity check, not here."""
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
    return len(a_words & b_words) == min(len(a_words), len(b_words))


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


_DIGIT_RE = re.compile(r"\d")


def _numeric_swap(a_object: str | None, b_object: str | None) -> bool:
    """Same slot with exchanged numbers ("4100" vs "4333"). The
    implicit gate admits these without a negation marker — numeric
    corrections never carry one ("changed to 4333"). Digit strings
    must both exist and differ; "Friday" vs "Wednesday" is not a
    swap (no digits), identical values are restatements, not flips."""
    if a_object is None or b_object is None:
        return False
    a_digits = "".join(_DIGIT_RE.findall(a_object))
    b_digits = "".join(_DIGIT_RE.findall(b_object))
    return bool(a_digits) and bool(b_digits) and a_digits != b_digits


def implicit_correction_gate(old_content: str, new_content: str,
                             old_subject: str | None,
                             new_subject: str | None,
                             old_object: str | None,
                             new_object: str | None,
                             old_predicate: str | None = None,
                             new_predicate: str | None = None,
                             mcos: float | None = None) -> bool:
    """Write-path guard for verifier-routed corrections. The observer
    routes NLI-contra pairs into the correction lane, but NLI misfires
    ~1.00 on same-template rows — live, it chained 6 supersedes across
    10 fan rows ("Bex's locker combo is 1002" killed "Tuli's locker
    combo is 1001") and ate 2 of 5 journey stops. An inferred
    contradiction is not established contradiction: implicit routing
    needs what the sweep needs. Same entity first (different people
    are different slots even when both values are numbers), then a
    numeric swap, then one slot with a flipped relation — a negation
    marker or a changed predicate ("drinks" -> "stopped drinking" is a
    reversal with no negation at all). Journey stops ("flew" vs
    "trucked") twin on different objects before predicates compare.
    Explicit corrections use explicit_veto below (marker-specific rules)."""
    if not entity_linked(old_subject, new_subject, old_content,
                         new_content, mcos):
        return False
    if _numeric_swap(old_object, new_object):
        return True
    if not _same_object(old_object, new_object):
        return False
    if _negation_asymmetry(old_content, new_content):
        return True
    # Predicate flip without a negation marker needs the slot EXACT:
    # the scribe drops arguments nondeterministically ("parcel" for
    # "trucked the parcel to Berlin"), and coverage would equate that
    # sparse triple with every elaborated one ("parcel to Frankfurt",
    # "parcel to Marta") — journey stops chain-murdered. A bare "did
    # X" -> "did Y" about provably the same object is a reversal; any
    # slot difference twins. Empty word-sets never equate (no slot
    # evidence either way).
    old_w = _object_words(old_object)
    new_w = _object_words(new_object)
    if not old_w or not new_w or old_w != new_w:
        return False
    old_p, new_p = _norm(old_predicate), _norm(new_predicate)
    return (old_p is not None and new_p is not None
            and old_p != new_p)


def explicit_veto(old_subject_raw: str | None, new_subject_raw: str | None,
                  old_object: str | None, new_object: str | None,
                  old_content: str, new_content: str,
                  mcos: float | None = None,
                  pool_singleton_session: bool = False) -> bool:
    """True = the marked correction must twin, never kill. A "Correction:"
    marker says THAT, never WHICH — the bound row still needs entity
    evidence, or elimination. Vetoes, each a pinned live murder: (1) the
    new turn names a proper identity disjoint from the old side ("Bex's
    ..." must never kill Tuli's); (2) no entity link plus a numeric swap
    (numbers alone never bridge disjoint generic entities — safe vs
    vault); (3) no link and no elimination (a subject-less bystander in
    a multi-row pool shares nothing with the correction). Linked pairs
    (G4 mention, D6 phrasal overlap, F1 masked shape, high-cos
    paraphrase) proceed, and so does a session pool holding exactly one
    row — the only thing the correction could mean (w1corr). F2a
    singletons don't count: a similarity target is a guess, and
    guesses need entity evidence. Residual: generic-disjoint-non-numeric
    explicit pairs are word-level-identical to G4's wording-variation
    and link — accepted for the pinned contract."""
    new_ids = _identity_words(new_subject_raw)
    if new_ids:
        old_side = (_subject_words(old_subject_raw)
                    | _content_words(old_content))
        if new_ids.isdisjoint(old_side):
            return True
    if entity_linked(old_subject_raw, new_subject_raw, old_content,
                     new_content, mcos):
        return False
    if _numeric_swap(old_object, new_object):
        return True
    return not pool_singleton_session


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

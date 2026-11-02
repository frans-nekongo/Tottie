"""Reconciler: the moment a new fact meets an old one. NEW/SKIP/UPDATE/SUPERSEDE.

Match (same owner + quarantine partition, live rows only):
  SP-equal (both non-null, ANY kind) OR (same kind AND cosine >= floor AND
  an anchor: shared tag or SP-partial). SP is a match HINT, not an identity
  (W10: scribe triples are guesses; generic SPs collide across unrelated
  rows); similarity stays typed so vibes never merge across claim types.
  SP-less event candidates skip matching (episodes accumulate); SP-bearing
  events match by identity only, never by cosine (episodes dedupe, never
  mush-merge).
Labile route (CORRECTION turns only): just-recalled rows match at the lower
active floor (0.60) with no anchor — single-token numeric edits score ~0.73
and would otherwise never reconcile (measured over 10 pairs).
Value compare on the winner: equal objects -> SKIP (bump old); differing
non-null objects -> SUPERSEDE (chain via supersedes + link) only when
contents agree (SUPERSEDE_COS) or correction intent is marked — else the
candidate inserts as a twin-NEW (SP twins are legal); null on either
side -> UPDATE (append/refresh), same twin guard.
Safety: quarantined candidates match quarantined rows only (poison can never
supersede a user fact); speech acts never supersede (requests are history).
Concurrency: match rows are FOR UPDATE locked inside the turn's transaction;
the idempotency hash backstops exact-retry races.
Labile-on-access: recall registers served ids here (10-min TTL); CORRECTION
turns prefer active matches (reconsolidation route).
"""
import hashlib
import time

from psycopg.types.json import Json

from ..db import pgvector_literal
from .cues import is_speech_act


def row_hash(session_id: str, turn: int, content: str) -> str:
    return hashlib.sha256(
        f"{session_id}:{turn}:{content}".encode()
    ).hexdigest()[:32]

QUARANTINE_TRUSTS = {"tool", "web", "model_inferred"}
# Trust ALONE gates quarantine. An earlier kind-dimension let any outside
# claim the LLM happened to label "event" walk past the immune system —
# a web "event" quarantined False and flaked the suite. The agent's own
# observations arrive as user_direct, so the "raw perception flows"
# intent is preserved exactly; kind is the LLM's guess, trust is the fact.
ACTIVE_TTL_S = 600.0
TAG_LINK_CAP = 3
# Correction floor: just above measured unrelated baseline (0.32, Batch-1),
# far below paraphrase. The match license is cue + session + recency +
# cosine-above-noise (all deterministic); kind equality and tag anchors
# only RANK (free emergent words vary run to run — gating on them flaked
# 25-50% live). Casual-'actually' turns clear the cue but die on the floor
# (unrelated pairs sit ~0.1-0.3).
CORRECTION_FLOOR = 0.35
# SUPERSEDE similarity floor: SP-equal alone is not identity (scribe SPs
# are guesses; generic triples like (owner, requires) collide across
# unrelated rows). A matched row is superseded only when contents agree
# this much — a same-slot value change looks near-identical, a generic
# collision looks distant. Measured both sides (bge-small): true updates
# hotel 0.750, vegetarian 0.796, ben 0.830, mascot 0.865, boston 0.893;
# false kills mission/h1 0.531, req/req 0.705 (speech-guarded first),
# h1-example/vocab 0.660, quarantine/process 0.647. Marked correction
# intent (via_correction) bypasses: the human said it is a correction.
SUPERSEDE_COS = 0.70
RECENT_SESSION_LIMIT = 5  # guess: correction referent is near by
# Kind/tier names leak into tags ("preference") and glue unrelated rows.
# They never form links on their own (the cheese-petite repair).
STOP_TAGS = frozenset({
    "fact", "preference", "decision", "lesson", "identity", "convention",
    "event", "doc", "episodic", "knowledge", "procedural",
})

_ACTIVE: dict[tuple[str, str], tuple[set[str], float]] = {}


def note_active(owner: str, session_id: str, ids: list[str]) -> None:
    now = time.monotonic()
    expired = [k for k, (_, ts) in _ACTIVE.items() if now - ts > ACTIVE_TTL_S]
    for k in expired:
        del _ACTIVE[k]
    if ids:
        _ACTIVE[(owner, session_id)] = (set(ids), now)


def get_active(owner: str, session_id: str) -> set[str]:
    hit = _ACTIVE.get((owner, session_id))
    if hit is None:
        return set()
    ids, ts = hit
    if time.monotonic() - ts > ACTIVE_TTL_S:
        del _ACTIVE[(owner, session_id)]
        return set()
    return set(ids)


async def recent_session_ids(conn, owner: str, session_id: str,
                             limit: int = 5) -> set[str]:
    """Correction fallback pool: a CORRECTION's referent is near by —
    same session, just said. When no labile registration exists (nothing
    was recalled first), the recent live rows of this session become the
    match pool at the active floor, so 'moved to Wednesday' still finds
    'due Friday' (0.81 >= 0.60) instead of duplicating it. Labile rows
    always take precedence; this only fills an empty pool."""
    cur = await conn.execute(
        "SELECT id FROM memories WHERE owner = %s AND valid_to IS NULL "
        "AND NOT quarantined AND source->>'session' = %s "
        "ORDER BY created_at DESC LIMIT %s",
        (owner, session_id, limit),
    )
    return {str(r["id"]) for r in await cur.fetchall()}


def is_quarantined(trust: str) -> bool:
    return trust in QUARANTINE_TRUSTS


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()).lower()


def _norm_tags(tags) -> list[str]:
    """Tags are machine tokens: strip, lowercase, dedupe, drop empties.
    Without this "Food" and "food" silently miss a must-link."""
    out: list[str] = []
    for t in tags or []:
        n = _norm(str(t))
        if n and n not in out:
            out.append(n)
    return out


async def _find_matches(conn, *, owner, kind, quarantined, cand, vec, floor,
                      identity_only: bool = False):
    cosine_leg = (
        " OR (kind = %s AND embedding <=> %s::vector <= %s AND (EXISTS "
        "(SELECT 1 FROM unnest(tags) t WHERE lower(btrim(t)) = ANY(%s)) "
        "OR (subject = %s AND %s::text IS NOT NULL) "
        "OR (predicate = %s AND %s::text IS NOT NULL)))"
        if not identity_only else ""
    )
    params: list = [
        pgvector_literal(vec), owner, quarantined,
        cand["subject"], cand["predicate"], cand["subject"], cand["predicate"],
    ]
    if not identity_only:
        params += [
            kind, pgvector_literal(vec), 1.0 - floor, cand["tags"] or [],
            cand["subject"], cand["subject"], cand["predicate"], cand["predicate"],
        ]
    cur = await conn.execute(
        "SELECT id, kind, subject, predicate, object, content, tags, "
        "salience, valid_to, embedding <=> %s::vector AS dist "
        "FROM memories WHERE owner = %s AND valid_to IS NULL "
        "AND quarantined = %s AND ("
        "  (subject IS NOT DISTINCT FROM %s AND predicate IS NOT DISTINCT FROM %s "
        "   AND %s::text IS NOT NULL AND %s::text IS NOT NULL)"
        f"{cosine_leg}"
        ") ORDER BY dist LIMIT 5 FOR UPDATE",
        tuple(params),
    )
    return await cur.fetchall()


async def _find_active(conn, *, owner, kind, quarantined, cand, vec, floor,
                     active: set[str], identity_only: bool = False):
    """Labile route: SP-equal or cosine >= active floor among just-recalled
    rows. No tag anchor: active rows are already context-bound to this turn."""
    cosine_leg = (
        " OR (kind = %s AND embedding <=> %s::vector <= %s)"
        if not identity_only else ""
    )
    params: list = [
        pgvector_literal(vec), owner, quarantined, sorted(active),
        cand["subject"], cand["predicate"], cand["subject"], cand["predicate"],
    ]
    if not identity_only:
        params += [kind, pgvector_literal(vec), 1.0 - floor]
    cur = await conn.execute(
        "SELECT id, kind, subject, predicate, object, content, tags, "
        "salience, valid_to, embedding <=> %s::vector AS dist "
        "FROM memories WHERE owner = %s AND valid_to IS NULL "
        "AND quarantined = %s AND id = ANY(%s::uuid[]) AND ("
        "  (subject IS NOT DISTINCT FROM %s AND predicate IS NOT DISTINCT FROM %s "
        "   AND %s::text IS NOT NULL AND %s::text IS NOT NULL)"
        f"{cosine_leg}"
        ") ORDER BY dist LIMIT 5 FOR UPDATE",
        tuple(params),
    )
    return await cur.fetchall()


async def _find_correction(conn, *, owner, kind, quarantined, cand, vec,
                         pool: set[str]):
    """Correction match: CORRECTION cue + recent-session pool + cosine
    above noise. SP-less rows (no doer/doing triple) can never SP-match
    and often sit below the similarity floors (live pair: 0.538); kind
    words and tag choices vary run to run, so they RANK (anchor, then
    kind, then distance) instead of gating. Fully deterministic given
    texts: same pair always matches the same row."""
    cur = await conn.execute(
        "SELECT id, kind, subject, predicate, object, content, tags, "
        "salience, valid_to, embedding <=> %s::vector AS dist "
        "FROM memories WHERE owner = %s AND valid_to IS NULL "
        "AND quarantined = %s AND id = ANY(%s::uuid[]) "
        "AND embedding <=> %s::vector <= %s "
        "ORDER BY EXISTS (SELECT 1 FROM unnest(tags) t "
        "WHERE lower(btrim(t)) = ANY(%s)) DESC, (kind = %s) DESC, "
        "embedding <=> %s::vector LIMIT 5 FOR UPDATE",
        (pgvector_literal(vec), owner, quarantined, sorted(pool),
         pgvector_literal(vec), 1.0 - CORRECTION_FLOOR,
         cand["tags"] or [], kind, pgvector_literal(vec)),
    )
    return await cur.fetchall()


def _pick(matches: list[dict], active: set[str]) -> dict | None:
    live = [m for m in matches if m["valid_to"] is None]
    if not live:
        return None
    live.sort(key=lambda m: (str(m["id"]) not in active, m["dist"]))
    return live[0]


async def _link(conn, *, owner, src, dst, relation, weight, reason) -> None:
    await conn.execute(
        "INSERT INTO memory_links (owner, src, dst, relation, weight, reason) "
        "VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s) "
        "ON CONFLICT (owner, src, dst, relation) DO NOTHING",
        (owner, src, dst, relation, weight, reason),
    )


async def _tag_links(conn, *, owner, quarantined, new_id, tags, kind):
    if not tags:
        return
    # Per-tag fan-out, not global top-N: a global salience cap lets one
    # hot tag starve every other facet (live case: the school<->company
    # bridge row linked 0 company rows because trace rows out-saliented
    # them). Each tag facet earns its own links.
    # Area tags are partitions, not relations: linking on area: wires
    # every row of a partition to every other (an h1 rule linked to
    # TERMINAL_SECRET rows via area:nkngo-documentation). Topic tags stay.
    mine = {t for t in set(tags) - STOP_TAGS - {_norm(kind) or ""}
            if not t.startswith("area:")}
    seen: dict[str, dict] = {}
    for tag in sorted(mine):
        cur = await conn.execute(
            "SELECT id, kind, tags FROM memories WHERE owner = %s AND valid_to IS NULL "
            "AND quarantined = %s AND id <> %s::uuid "
            "AND EXISTS (SELECT 1 FROM unnest(tags) t "
            "WHERE lower(btrim(t)) = %s) "
            "ORDER BY salience DESC LIMIT %s",
            (owner, quarantined, new_id, tag, TAG_LINK_CAP),
        )
        for r in await cur.fetchall():
            seen.setdefault(str(r["id"]), r)
    for r in seen.values():
        theirs = ({_norm(t) for t in (r["tags"] or [])} - {None}
                  - STOP_TAGS - {_norm(r["kind"]) or ""})
        shared = sorted(mine & theirs)
        if not shared:
            continue  # overlap was kind-namespace only: no link (mush guard)
        await _link(
            conn, owner=owner, src=new_id, dst=str(r["id"]),
            relation="tag", weight=1.0,
            reason=f"shared tag: {', '.join(shared)}",
        )


def _turn_of(source: dict | None) -> int | None:
    try:
        return int((source or {}).get("turn"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


async def _temporal_link(conn, *, owner, quarantined, new_id, turn):
    """Session before/after chain (the linked list): the previously spoken
    live row points at the new one, so the arrow and the story agree on
    before -> after. Predecessor is the greatest logical turn below this
    one — NEVER created_at: under concurrency created_at is processing
    order, and the chain ran backwards (turn 1 -> turn 0, seen live).
    One edge per memory: bounded. Concurrent twins can share one
    predecessor; relink completes the chain offline."""
    cur = await conn.execute(
        "SELECT id, source FROM memories WHERE owner = %s AND valid_to IS NULL "
        "AND quarantined = %s AND id <> %s::uuid "
        "AND source->>'session' = %s "
        "AND source->>'turn' ~ '^[0-9]+$' "
        "AND (source->>'turn')::int < %s "
        "ORDER BY (source->>'turn')::int DESC, created_at DESC LIMIT 1",
        (owner, quarantined, new_id, turn.session_id, turn.turn),
    )
    prev = await cur.fetchone()
    if prev is None:
        return
    prev_turn = _turn_of(prev["source"])
    await _link(
        conn, owner=owner, src=str(prev["id"]), dst=new_id,
        relation="temporal", weight=0.8,
        reason=f"session order: turn {prev_turn} -> turn {turn.turn}",
    )


# Transient process narration (observer-flagged) starts near-zero
# stability: R(t) = exp(-age/0.15) falls under the ranker's 0.05 floor
# in ~11h, so status chatter retires at a sleep sweep instead of
# diluting recall forever. Still revivable: re-mention rehearses
# stability back up. Principle/identity candidates are never
# transient (a reusable rule or self-fact is durable by definition),
# enforced here so a sloppy flag can't sink them.
TRANSIENT_STABILITY = 0.15


async def _insert_new(conn, *, turn, obs, cand, vec, model, quarantined,
                      supersedes: str | None = None) -> str:
    transient = bool(cand.get("transient")) and not (
        cand.get("principle") or "").strip() and cand.get("tier") != "identity"
    stability = TRANSIENT_STABILITY if transient else 1.0
    cur = await conn.execute(
        'INSERT INTO memories (owner, tier, kind, subject, predicate, "object", '
        "content, tags, principle, salience, surprise, arousal, trust, source, "
        "embedding, embedding_model, hash, quarantined, needs_curation, "
        "supersedes, stability) VALUES "
        "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (owner, hash) WHERE hash IS NOT NULL "
        "DO NOTHING RETURNING id",
        (
            turn.owner, cand["tier"], cand["kind"], cand["subject"],
            cand["predicate"], cand["object"], cand["content"], cand["tags"],
            cand["principle"], obs.salience, obs.surprise, obs.surprise,
            turn.trust,
            Json({
                "session": turn.session_id, "turn": turn.turn,
                "origin": turn.origin, "client_event_id": turn.client_event_id,
            }),
            pgvector_literal(vec), model,
            row_hash(turn.session_id, turn.turn, cand["content"]),
            quarantined, obs.raw_fallback,
            supersedes, stability,
        ),
    )
    row = await cur.fetchone()
    if row is None:  # lost a race with our own retry: look up the winner
        cur = await conn.execute(
            "SELECT id FROM memories WHERE owner = %s AND hash = %s",
            (turn.owner, row_hash(turn.session_id, turn.turn, cand["content"])),
        )
        row = await cur.fetchone()
    new_id = str(row["id"])
    if supersedes:
        await _link(
            conn, owner=turn.owner, src=new_id, dst=supersedes,
            relation="supersedes", weight=1.0,
            reason="newer truth replaced this row (valid_to set)",
        )
    await _tag_links(
        conn, owner=turn.owner, quarantined=quarantined,
        new_id=new_id, tags=cand["tags"] or [], kind=cand["kind"],
    )
    await _temporal_link(
        conn, owner=turn.owner, quarantined=quarantined,
        new_id=new_id, turn=turn,
    )
    return new_id


async def _find_live_sp(conn, *, owner: str, quarantined: bool,
                      subject: str, predicate: str, vec) -> dict | None:
    """Exact-SP fallback (G7): vector matching can miss a live row sharing
    the candidate's triple when contents are distant. SP twins are legal
    (W10), so this returns the NEWEST twin — the current truth — and the
    downstream compare decides SUPERSEDE vs twin-NEW on similarity, never
    on SP alone (SP-equal with distant contents murdered the mission
    statement: (owner, requires) is not an identity)."""
    cur = await conn.execute(
        'SELECT id, kind, subject, predicate, "object", content, tags, '
        "salience, valid_to, embedding <=> %s::vector AS dist FROM memories "
        "WHERE owner = %s AND subject = %s AND predicate = %s "
        "AND quarantined = %s AND valid_to IS NULL "
        "ORDER BY created_at DESC LIMIT 1 FOR UPDATE",
        (pgvector_literal(vec), owner, subject, predicate, quarantined),
    )
    return await cur.fetchone()


async def apply_candidate(conn, *, turn, obs, cand, vec, model, floor,
                          active_floor, active: set[str],
                          correction_pool: set[str] | None = None) -> dict:
    """Reconcile one embedded candidate inside the turn's transaction."""
    cand = {**cand, "tags": _norm_tags(cand.get("tags"))}
    quarantined = is_quarantined(turn.trust)
    has_sp = cand.get("subject") is not None and cand.get("predicate") is not None
    if (cand["kind"] == "event" or obs.raw_fallback) and not has_sp:
        mid = await _insert_new(
            conn, turn=turn, obs=obs, cand=cand, vec=vec, model=model,
            quarantined=quarantined,
        )
        return {"op": "RAW" if obs.raw_fallback else "NEW", "memory_id": mid,
                "superseded_id": None}
    # SP-bearing candidates always reconcile (an event that names a triple
    # is a claim wearing an episode costume). SP is a match hint, not an
    # identity: twins are legal (W10) and similarity decides (SUPERSEDE_COS).
    if has_sp:
        # Serialise same-SP writers: the dropped unique index used to
        # serialise them (losers 500ed and retried into a chain); without
        # it, concurrent near-identical claims twin instead of chaining.
        # Transaction-scoped, auto-released, keyed by slot + partition.
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"{turn.owner}:{quarantined}:{cand['subject']}:"
             f"{cand['predicate']}",),
        )
    identity_only = cand["kind"] == "event"
    match = None
    via_correction = False
    for _ in range(3):  # re-find if our locked pick died underneath us
        matches: list[dict] = []
        targeted = False
        if active:
            # Active is non-empty only for corrections (scribe gates it on
            # cue/target), so an active match is correction-targeted too.
            matches = await _find_active(
                conn, owner=turn.owner, kind=cand["kind"],
                quarantined=quarantined, cand=cand, vec=vec,
                floor=active_floor, active=active,
                identity_only=identity_only,
            )
            targeted = bool(matches)
        elif correction_pool:
            matches = await _find_correction(
                conn, owner=turn.owner, kind=cand["kind"],
                quarantined=quarantined, cand=cand, vec=vec,
                pool=correction_pool,
            )
            targeted = bool(matches)
        if not matches:
            matches = await _find_matches(
                conn, owner=turn.owner, kind=cand["kind"],
                quarantined=quarantined, cand=cand, vec=vec, floor=floor,
                identity_only=identity_only,
            )
            targeted = False
        match = _pick(matches, active)
        if match is not None or not matches:
            via_correction = targeted and match is not None
            break
    # G4: subject agreement gates every update. A match across different
    # named subjects is a different fact (entity-linked updating: Mem0,
    # sentient #268) — except on the correction lane, where marked human
    # intent / NLI-verified aboutness IS the subject check (scribe wording
    # varies: "rebrand" vs "deadline" name one entity). SP-less rows can't
    # gate and journal below.
    m_sub = _norm(match.get("subject")) if match is not None else None
    c_sub = _norm(cand.get("subject"))
    diff_sub = (m_sub is not None and c_sub is not None
                and m_sub != c_sub)
    same_sub = (m_sub is not None and c_sub is not None
                and m_sub == c_sub)
    if match is not None and diff_sub and not via_correction:
        match = None
    # G7: the candidate's own slot is consulted when nothing else
    # matched (LIMIT-5 eviction, or a correction-pool pick). SP twins are
    # legal (W10), so a live slot twin is only ever a compare CANDIDATE:
    # similarity decides SUPERSEDE vs twin-NEW. There is no co-retire:
    # retiring the candidate's slot alongside a rival murdered innocent
    # rows (an H1-rule row died beside a vocab rival sharing only a
    # generic SP) and the unique index it served is gone.
    if has_sp:
        slot = await _find_live_sp(
            conn, owner=turn.owner, quarantined=quarantined,
            subject=cand["subject"], predicate=cand["predicate"], vec=vec,
        )
        if match is None:
            # Same subject by construction: no G4 gate. Downstream
            # compare decides SUPERSEDE vs SKIP vs UPDATE vs twin-NEW.
            match = slot
            if match is not None:
                m_sub = _norm(match.get("subject"))
                same_sub = (m_sub is not None and c_sub is not None
                            and m_sub == c_sub)
    if match is None:
        mid = await _insert_new(
            conn, turn=turn, obs=obs, cand=cand, vec=vec, model=model,
            quarantined=quarantined,
        )
        return {"op": "NEW", "memory_id": mid, "superseded_id": None}
    old_id = str(match["id"])
    old_obj, new_obj = _norm(match["object"]), _norm(cand["object"])
    old_pred, new_pred = (
        _norm(match.get("predicate")), _norm(cand.get("predicate")))
    # Same entity + flipped predicate ("does not drink" -> "drinks") is a
    # belief change even when the object is identical — object-only compare
    # SKIPped it as a restatement (G1 layer 2). Holds on any path: same
    # subject plus any SP difference is an update, full SP match a dup.
    pred_flipped = (
        same_sub and old_obj is not None and new_obj is not None
        and old_pred is not None and new_pred is not None
        and old_pred != new_pred)
    # Twin guard (W10): without marked correction intent, a distant or
    # speech-act match is a sibling, not the same slot — it inserts as a
    # twin instead of murdering the match. Fail closed: a missing dist
    # reads as maximally distant, never as similar.
    mcos = 1.0 - float(match.get("dist", 1.0))
    twin = not via_correction and (
        is_speech_act(match.get("content"), match.get("predicate"))
        or is_speech_act(cand["content"], cand.get("predicate"))
        or mcos < SUPERSEDE_COS
    )
    if ((old_obj is not None and new_obj is not None
         and old_obj != new_obj) or pred_flipped):
        if twin:
            mid = await _insert_new(
                conn, turn=turn, obs=obs, cand=cand, vec=vec, model=model,
                quarantined=quarantined,
            )
            return {"op": "NEW", "memory_id": mid,
                    "superseded_id": None}
        await conn.execute(
            "UPDATE memories SET valid_to = now() WHERE id = %s::uuid",
            (old_id,),
        )
        mid = await _insert_new(
            conn, turn=turn, obs=obs, cand=cand, vec=vec, model=model,
            quarantined=quarantined, supersedes=old_id,
        )
        return {"op": "SUPERSEDE", "memory_id": mid, "superseded_id": old_id}
    if old_obj is not None and new_obj is not None:
        await conn.execute(
            "UPDATE memories SET confidence = LEAST(1.0, confidence + 0.1), "
            "salience = GREATEST(salience, %s), last_access = now(), "
            "access_count = access_count + 1 WHERE id = %s::uuid",
            (obs.salience, old_id),
        )
        return {"op": "SKIP", "memory_id": old_id, "superseded_id": None}
    if twin:
        # Same guard for the merge lane: appending distant content to a
        # matched row would mush two facts into one franken-row (U3 owns
        # splitting; until then, twins stay separate rows).
        mid = await _insert_new(
            conn, turn=turn, obs=obs, cand=cand, vec=vec, model=model,
            quarantined=quarantined,
        )
        return {"op": "NEW", "memory_id": mid, "superseded_id": None}
    merged_tags = list(dict.fromkeys((match["tags"] or []) + (cand["tags"] or [])))
    # Provenance follows the merge: appended content comes from THIS
    # turn, so source.turns accumulates or the curator's drift check
    # (row vs original turn only) convicts true merged rows.
    cur = await conn.execute(
        "SELECT source FROM memories WHERE id = %s::uuid", (old_id,))
    src_row = await cur.fetchone()
    old_source = dict(src_row["source"] or {}) if src_row else {}
    turns = list(old_source.get("turns") or [])
    if not turns and old_source.get("turn") is not None:
        turns = [old_source["turn"]]
    if turn.turn not in turns:
        turns.append(turn.turn)
    old_source["turns"] = turns
    await conn.execute(
        'UPDATE memories SET content = content || %s, summary = %s, '
        '"object" = COALESCE("object", %s), tags = %s, '
        "salience = GREATEST(salience, %s), "
        "confidence = LEAST(1.0, confidence + 0.1), surprise = %s, "
        "source = %s, last_access = now() WHERE id = %s::uuid",
        (
            "\n" + cand["content"], cand["content"][:300], cand["object"],
            merged_tags, obs.salience, obs.surprise, Json(old_source),
            old_id,
        ),
    )
    return {"op": "UPDATE", "memory_id": old_id, "superseded_id": None}

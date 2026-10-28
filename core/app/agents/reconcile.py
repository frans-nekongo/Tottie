"""Reconciler: the moment a new fact meets an old one. NEW/SKIP/UPDATE/SUPERSEDE.

Match (same owner + quarantine partition, live rows only):
  SP-equal (both non-null, ANY kind) OR (same kind AND cosine >= floor AND
  an anchor: shared tag or SP-partial). Identity is exact so it crosses
  kinds (kind is the LLM's guess; the SP triple is the fact); similarity
  stays typed so vibes never merge across claim types. SP-less event
  candidates skip matching (episodes accumulate); SP-bearing events match
  by identity only, never by cosine (episodes dedupe, never mush-merge).
Labile route (CORRECTION turns only): just-recalled rows match at the lower
active floor (0.60) with no anchor — single-token numeric edits score ~0.73
and would otherwise never reconcile (measured over 10 pairs).
Value compare on the winner: equal objects -> SKIP (bump old); differing
non-null objects -> SUPERSEDE (chain via supersedes + link); null on either
side -> UPDATE (append/refresh).
Safety: quarantined candidates match quarantined rows only (poison can never
supersede a user fact). Concurrency: match rows are FOR UPDATE locked inside
the turn's transaction; the live-SP unique index backstops SP races and the
Scribe retries once on violation.
Labile-on-access: recall registers served ids here (10-min TTL); CORRECTION
turns prefer active matches (reconsolidation route).
"""
import hashlib
import time

from psycopg.types.json import Json

from ..db import pgvector_literal


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
    cur = await conn.execute(
        "SELECT id, kind, tags FROM memories WHERE owner = %s AND valid_to IS NULL "
        "AND quarantined = %s AND id <> %s::uuid "
        "AND EXISTS (SELECT 1 FROM unnest(tags) t "
        "WHERE lower(btrim(t)) = ANY(%s)) "
        "ORDER BY salience DESC LIMIT %s",
        (owner, quarantined, new_id, tags, TAG_LINK_CAP),
    )
    mine = set(tags) - STOP_TAGS - {_norm(kind) or ""}
    for r in await cur.fetchall():
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


async def _insert_new(conn, *, turn, obs, cand, vec, model, quarantined,
                      supersedes: str | None = None) -> str:
    cur = await conn.execute(
        'INSERT INTO memories (owner, tier, kind, subject, predicate, "object", '
        "content, tags, principle, salience, surprise, trust, source, "
        "embedding, embedding_model, hash, quarantined, needs_curation, "
        "supersedes) VALUES "
        "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s,%s,%s,%s) "
        "ON CONFLICT (owner, hash) WHERE hash IS NOT NULL "
        "DO NOTHING RETURNING id",
        (
            turn.owner, cand["tier"], cand["kind"], cand["subject"],
            cand["predicate"], cand["object"], cand["content"], cand["tags"],
            cand["principle"], obs.salience, obs.surprise, turn.trust,
            Json({
                "session": turn.session_id, "turn": turn.turn,
                "origin": turn.origin, "client_event_id": turn.client_event_id,
            }),
            pgvector_literal(vec), model,
            row_hash(turn.session_id, turn.turn, cand["content"]),
            quarantined, obs.raw_fallback,
            supersedes,
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


async def apply_candidate(conn, *, turn, obs, cand, vec, model, floor,
                          active_floor, active: set[str]) -> dict:
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
    # SP is identity: SP-bearing candidates always reconcile (an event that
    # names a triple is a claim wearing an episode costume, and the live-SP
    # index would kill a blind insert — seen live on the hotel correction).
    identity_only = cand["kind"] == "event"
    match = None
    for _ in range(3):  # re-find if our locked pick died underneath us
        matches: list[dict] = []
        if active:
            matches = await _find_active(
                conn, owner=turn.owner, kind=cand["kind"],
                quarantined=quarantined, cand=cand, vec=vec,
                floor=active_floor, active=active,
                identity_only=identity_only,
            )
        if not matches:
            matches = await _find_matches(
                conn, owner=turn.owner, kind=cand["kind"],
                quarantined=quarantined, cand=cand, vec=vec, floor=floor,
                identity_only=identity_only,
            )
        match = _pick(matches, active)
        if match is not None or not matches:
            break
    if match is None:
        mid = await _insert_new(
            conn, turn=turn, obs=obs, cand=cand, vec=vec, model=model,
            quarantined=quarantined,
        )
        return {"op": "NEW", "memory_id": mid, "superseded_id": None}
    old_id = str(match["id"])
    old_obj, new_obj = _norm(match["object"]), _norm(cand["object"])
    if old_obj is not None and new_obj is not None and old_obj != new_obj:
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
    merged_tags = list(dict.fromkeys((match["tags"] or []) + (cand["tags"] or [])))
    await conn.execute(
        'UPDATE memories SET content = content || %s, summary = %s, '
        '"object" = COALESCE("object", %s), tags = %s, '
        "salience = GREATEST(salience, %s), "
        "confidence = LEAST(1.0, confidence + 0.1), surprise = %s, "
        "last_access = now() WHERE id = %s::uuid",
        (
            "\n" + cand["content"], cand["content"][:300], cand["object"],
            merged_tags, obs.salience, obs.surprise, old_id,
        ),
    )
    return {"op": "UPDATE", "memory_id": old_id, "superseded_id": None}

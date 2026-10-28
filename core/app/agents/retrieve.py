"""Associative recall: three legs, RRF fusion, spreading activation, card.

Ranked branch: identity slice (unconditional) + vector/lexical/associative legs
in ONE statement + RRF(k=60) + 2-hop BFS over memory_links + confidence with
honest abstain + 400-token Context Card + retrieval story path.
Replay branch (recency cues): ordered session events, no similarity search.
Every recall fires due intentions inline, bumps access_counts (rehearsal on
access), and appends a recall event to the ledger (cue set, so replay skips it).
"""
import time
from datetime import datetime, timedelta, timezone

from ..db import pgvector_literal
from . import cues

RRF_K = 60
OVERFETCH = 50
BFS_HOPS = 2
BFS_NODES = 50
BFS_DECAY = 0.5
CARD_CHARS = 1600  # ~400 tokens at the codebase's chars/4 heuristic
COMMAND_BOOST = 1.5
COMMAND_KINDS = {"convention", "decision", "lesson"}
BFS_BUDGET_S = 0.25


def _legs_sql(tiered: bool) -> str:
    tier = "AND tier = ANY(%s)" if tiered else ""
    return f"""
SELECT id, leg, rnk FROM (
  SELECT id, 'v' AS leg, row_number() OVER (ORDER BY d) AS rnk FROM (
    SELECT id, embedding <=> %s::vector AS d FROM memories
    WHERE owner = %s AND valid_to IS NULL AND NOT quarantined
      AND embedding IS NOT NULL {tier}
    ORDER BY d LIMIT {OVERFETCH}
  ) v
  UNION ALL
  SELECT id, 'f' AS leg, row_number() OVER (ORDER BY r DESC) AS rnk FROM (
    SELECT id, ts_rank(to_tsvector('english', content),
      plainto_tsquery('english', %s)) AS r FROM memories
    WHERE owner = %s AND valid_to IS NULL AND NOT quarantined
      AND to_tsvector('english', content) @@ plainto_tsquery('english', %s)
      {tier}
    ORDER BY r DESC LIMIT {OVERFETCH}
  ) f
  UNION ALL
  SELECT id, 'a' AS leg, row_number() OVER (
    ORDER BY salience DESC, utility DESC) AS rnk FROM (
    SELECT id, salience, utility FROM memories
    WHERE owner = %s AND valid_to IS NULL AND NOT quarantined
      AND tags && %s {tier}
    ORDER BY salience DESC, utility DESC LIMIT {OVERFETCH}
  ) a
) u"""


def _rrf(rows: list[dict]) -> dict[str, dict]:
    fused: dict[str, dict] = {}
    for r in rows:
        mid = str(r["id"])
        slot = fused.setdefault(mid, {"score": 0.0, "legs": {}})
        slot["score"] += 1.0 / (RRF_K + r["rnk"])
        slot["legs"][r["leg"]] = r["rnk"]
    return fused


async def check_intentions(db, owner: str, entities: list[str]) -> list[dict]:
    """Fire pending intentions whose time_cue passed or event_cue overlaps."""
    clauses = ["(time_cue IS NOT NULL AND time_cue <= now())"]
    params: list = [owner]
    for e in entities[:12]:
        clauses.append(r"(event_cue IS NOT NULL AND event_cue ILIKE %s ESCAPE '\')")
        lit = e.lstrip("#@").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params.append(f"%{lit}%")
    rows = await db.fetch(
        "UPDATE intentions SET status = 'fired', fired_at = now() "
        f"WHERE owner = %s AND status = 'pending' AND ({' OR '.join(clauses)}) "
        "RETURNING id, content, event_cue, time_cue",
        tuple(params),
    )
    return [
        {
            "id": str(r["id"]), "content": r["content"],
            "event_cue": r["event_cue"],
            "time_cue": r["time_cue"].isoformat() if r["time_cue"] else None,
        }
        for r in rows
    ]


async def _bfs(db, owner: str, seeds: list[str], deadline: float) -> dict[str, dict]:
    """2-hop walk over memory_links. Returns {id: {act, via}} for linked rows."""
    act = {s: 1.0 for s in seeds}
    found: dict[str, dict] = {}
    frontier = list(seeds)
    for _ in range(BFS_HOPS):
        if not frontier or time.monotonic() > deadline:
            break
        rows = await db.fetch(
            "SELECT src, dst, relation, weight FROM memory_links "
            "WHERE owner = %s AND src = ANY(%s::uuid[])",
            (owner, frontier),
        )
        frontier = []
        for r in rows:
            dst = str(r["dst"])
            if dst in act:
                continue  # cycle guard
            a = act[str(r["src"])] * BFS_DECAY * float(r["weight"] or 1.0)
            act[dst] = a
            found[dst] = {"act": a, "via": r["relation"], "from": str(r["src"])}
            frontier.append(dst)
            if len(act) >= BFS_NODES + len(seeds):
                break
    return found


def _confidence(fused: list[tuple[str, dict]], entities: list[str],
                rows: dict[str, dict]) -> tuple[float, float]:
    """margin = (top1-top2)/top1 blended 0.7/0.3 with entity coverage."""
    if not fused:
        return 0.0, 0.0
    top1 = fused[0][1]["score"]
    top2 = fused[1][1]["score"] if len(fused) > 1 else 0.0
    margin = max(0.0, (top1 - top2) / top1) if top1 > 0 else 0.0
    if not entities:
        return round(0.7 * margin + 0.3 * 1.0, 3), round(margin, 3)
    covered = 0
    bag = " ".join(
        " ".join((rows[m]["tags"] or [])) + " " + (rows[m]["content"] or "")[:500]
        for m, _ in fused[:8] if m in rows
    ).lower()
    for e in entities:
        if e.lstrip("#@").lower() in bag:
            covered += 1
    cov = covered / len(entities)
    return round(0.7 * margin + 0.3 * cov, 3), round(margin, 3)


def _why(legs: dict, cue_type: str) -> str:
    parts = []
    if "v" in legs:
        parts.append(f"vector #{legs['v']}")
    if "f" in legs:
        parts.append(f"lexical #{legs['f']}")
    if "a" in legs:
        parts.append(f"tag #{legs['a']}")
    return f"{cue_type} -> {' + '.join(parts)}"


async def _bump_access(db, ids: list[str]) -> None:
    if ids:
        await db.execute(
            "UPDATE memories SET access_count = access_count + 1, "
            "last_access = now() WHERE id = ANY(%s::uuid[])",
            (ids,),
        )


async def _register_reminder(db, owner: str, draft: dict) -> dict | None:
    if not draft or not draft["content"]:
        return None
    delta = timedelta(days=draft["days"], hours=draft["hours"])
    time_cue = (
        datetime.now(timezone.utc) + delta if delta.total_seconds() > 0 else None
    )
    row = await db.execute_returning(
        "INSERT INTO intentions (owner, content, event_cue, time_cue) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (owner, draft["content"], draft["event_cue"], time_cue),
    )
    return {
        "id": str(row["id"]), "content": draft["content"],
        "event_cue": draft["event_cue"],
        "time_cue": time_cue.isoformat() if time_cue else None,
    }


def _card(identity: list[dict], hits: list[dict], abstain: bool) -> str | None:
    if abstain and not identity:
        return None
    lines = []
    for r in identity:
        lines.append(f"- {r['content']}"[:200])
    head = "# who you are\n" + "\n".join(lines) if lines else ""
    body = []
    if not abstain:
        for h in hits:
            if h["tier"] == "identity":
                continue
            body.append(f"- [{h['tier']}/{h['kind']}] {h['summary']} ({h['why']})")
    chunks = [c for c in (head, "# context\n" + "\n".join(body) if body else "") if c]
    tags: list[str] = []
    for h in hits:
        tags += [t for t in h["tags"] if t not in tags]
    if tags[:6]:
        chunks.append("probe deeper: " + " ".join(f"#{t}" for t in tags[:6]))
    text = "\n\n".join(chunks)
    return text[:CARD_CHARS]


async def _contiguity(db, owner: str, winner: dict) -> list[str]:
    """Winner + same-session episodic neighbours by created_at (contiguity)."""
    path = [str(winner["id"])]
    session = (winner.get("source") or {}).get("session")
    if not session:
        return path
    rows = await db.fetch(
        "SELECT id, created_at FROM memories WHERE owner = %s AND tier = 'episodic' "
        "AND valid_to IS NULL AND NOT quarantined AND source->>'session' = %s "
        "AND id <> %s::uuid ORDER BY created_at",
        (owner, session, path[0]),
    )
    if not rows:
        return path
    before = [r for r in rows if r["created_at"] <= winner["created_at"]]
    after = [r for r in rows if r["created_at"] > winner["created_at"]]
    if before:
        path.insert(0, str(before[-1]["id"]))
    if after:
        path.append(str(after[0]["id"]))
    return path


async def _recall_event(db, session_id: str, query: str, cue: cues.Cue,
                        mode: str, confidence: float, abstain: bool,
                        n: int, latency_ms: int) -> None:
    from psycopg.types.json import Json

    await db.execute(
        "INSERT INTO memory_events (session_id, utterance, observer_verdict, "
        "scribe_action, cue, latency_ms, tokens) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (
            session_id, query,
            Json({"recall": True, "confidence": confidence, "abstain": abstain}),
            Json({"op": "RECALL", "mode": mode, "n": n}),
            Json({"type": cue.type, "entities": cue.entities, "policy": cue.policy}),
            latency_ms, 0,
        ),
    )


async def recall(*, db, embedder, owner: str, query: str, session_id: str,
                 k: int, tiers: list[str] | None, settings) -> dict:
    t0 = time.monotonic()
    cue = cues.classify(query)
    fired = await check_intentions(db, owner, cue.entities)
    registered = None
    if cue.type == "COMMAND":
        draft = cues.parse_reminder(query)
        if draft:
            registered = await _register_reminder(db, owner, draft)
    if cue.replay:
        out = await _replay(db, owner, session_id, settings)
    else:
        out = await _ranked(db, embedder, owner, query, cue, k, tiers, settings)
    out["fired_intentions"] = fired
    out["registered_intention"] = registered
    out["cue"] = {"type": cue.type, "entities": cue.entities, "policy": cue.policy}
    latency_ms = int((time.monotonic() - t0) * 1000)
    out["latency_ms"] = latency_ms
    await _recall_event(db, session_id, query, cue, out["mode"],
                        out["confidence"], out["abstain"], len(out["hits"]),
                        latency_ms)
    return out


async def _ranked(db, embedder, owner, query, cue, k, tiers, settings) -> dict:
    vec, _ = await embedder.embed(query, is_query=True)
    tags = [e[1:] for e in cue.entities if e.startswith(("#", "@"))]
    tiered = bool(tiers)
    params: list = [pgvector_literal(vec), owner]
    if tiered:
        params.append(tiers)
    params += [query, owner, query]
    if tiered:
        params.append(tiers)
    params += [owner, tags]
    if tiered:
        params.append(tiers)
    rows = await db.fetch(_legs_sql(tiered), tuple(params))
    fused = _rrf(rows)
    candidates_matched = len({str(r["id"]) for r in rows})
    identity = await db.fetch(
        "SELECT id, content FROM memories WHERE owner = %s AND tier = 'identity' "
        "AND valid_to IS NULL AND NOT quarantined ORDER BY salience DESC LIMIT 5",
        (owner,),
    )
    # Identity bypasses ranking entirely: card header only, never a hit.
    ordered = sorted(fused.items(), key=lambda kv: -kv[1]["score"])
    fetch_ids = [m for m, _ in ordered[: k + 8]]
    grown: dict[str, dict] = {}
    if fetch_ids:
        grown = await _bfs(db, owner, fetch_ids[:k] or fetch_ids,
                           time.monotonic() + BFS_BUDGET_S)
    want = list(dict.fromkeys(fetch_ids + list(grown)))
    by_id = {}
    if want:
        for r in await db.fetch(
            "SELECT id, tier, kind, content, summary, tags, trust, salience, "
            "utility, source, created_at FROM memories WHERE id = ANY(%s::uuid[])",
            (want,),
        ):
            by_id[str(r["id"])] = r
    if cue.policy == "command":
        for mid, slot in fused.items():
            row = by_id.get(mid)
            if row and row["kind"] in COMMAND_KINDS:
                slot["score"] *= COMMAND_BOOST
        ordered = sorted(fused.items(), key=lambda kv: -kv[1]["score"])
    for mid, g in grown.items():
        if mid not in fused and g["act"] >= 0.25 and mid in by_id:
            fused[mid] = {"score": g["act"] * 0.01, "legs": {},
                          "via": f"associated via {g['via']}"}
    ordered = sorted(fused.items(), key=lambda kv: -kv[1]["score"])
    confidence, margin = _confidence(ordered, cue.entities, by_id)
    abstain = confidence < settings.confidence_floor
    hits = []
    for mid, slot in ordered[:k]:
        row = by_id.get(mid)
        if row is None:
            continue
        text = row["content"] or ""
        hits.append({
            "id": mid, "tier": row["tier"], "kind": row["kind"],
            "summary": (row["summary"] or text)[:300], "tags": row["tags"] or [],
            "score": round(slot["score"], 4), "trust": row["trust"],
            "why": slot.get("via") or _why(slot["legs"], cue.type),
        })
    await _bump_access(db, [h["id"] for h in hits] + [str(r["id"]) for r in identity])
    path: list[str] = []
    if hits and not abstain:
        winner = by_id.get(hits[0]["id"])
        if winner is not None:
            path = await _contiguity(db, owner, winner)
    return {
        "mode": "ranked", "card": _card(identity, hits, abstain),
        "hits": hits, "confidence": confidence, "abstain": abstain,
        "margin": margin, "path": path, "candidates_matched": candidates_matched,
    }


async def _replay(db, owner: str, session_id: str, settings) -> dict:
    events = await db.fetch(
        "SELECT id, turn, utterance, scribe_action FROM memory_events "
        "WHERE session_id = %s AND cue IS NULL AND utterance IS NOT NULL "
        "ORDER BY id LIMIT %s",
        (session_id, settings.replay_n),
    )
    if not events:
        return {
            "mode": "replay", "card": None, "hits": [], "timeline": [],
            "confidence": 0.0, "abstain": True, "margin": 0.0, "path": [],
            "candidates_matched": 0,
        }
    mids: list[str] = []
    for e in events:
        for mid in ((e["scribe_action"] or {}).get("memory_ids") or []):
            if mid not in mids:
                mids.append(mid)
    by_id = {}
    if mids:
        for r in await db.fetch(
            "SELECT id, tier, kind, content, summary, tags, trust FROM memories "
            "WHERE id = ANY(%s::uuid[]) AND valid_to IS NULL AND NOT quarantined",
            (mids,),
        ):
            by_id[str(r["id"])] = r
    hits, timeline = [], []
    for e in events:
        kept = []
        for mid in ((e["scribe_action"] or {}).get("memory_ids") or []):
            row = by_id.get(mid)
            if row is None:
                continue
            kept.append((row["summary"] or row["content"])[:160])
            if mid not in {h["id"] for h in hits}:
                text = row["content"] or ""
                hits.append({
                    "id": mid, "tier": row["tier"], "kind": row["kind"],
                    "summary": (row["summary"] or text)[:300],
                    "tags": row["tags"] or [], "score": 1.0,
                    "trust": row["trust"], "why": f"replay turn {e['turn']}",
                })
        timeline.append({
            "turn": e["turn"], "utterance": (e["utterance"] or "")[:200],
            "kept": kept,
        })
    await _bump_access(db, [h["id"] for h in hits])
    lines = [f"{t['turn']}: {t['utterance']}" for t in timeline]
    kept_lines = [f"  -> {k}" for t in timeline for k in t["kept"]]
    card = "# session replay\n" + "\n".join(lines + kept_lines)
    return {
        "mode": "replay", "card": card[:CARD_CHARS], "hits": hits,
        "timeline": timeline, "confidence": 1.0, "abstain": False,
        "margin": 1.0, "path": [h["id"] for h in hits],
        "candidates_matched": len(events),
    }

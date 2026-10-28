"""Ambient briefing: the brain surfacing without being asked.

The agent calls this once per turn with the latest stimulus (or nothing).
No text given: brief on the session's own recent utterances — pure ambient.
Always included: due intentions (time dues fire with no entity match), and
memories formed since the caller's cursor (stateless: pass since_event_id,
get back event_id). The returned `briefing` block is pre-formatted to paste
straight into an agent's working context.
"""
from . import retrieve

CONTEXT_TURNS = 3


async def _stimulus(db, session_id: str, text: str | None) -> str:
    if (text or "").strip():
        return text.strip()
    rows = await db.fetch(
        "SELECT utterance FROM memory_events WHERE session_id = %s "
        "AND cue IS NULL AND utterance IS NOT NULL "
        "ORDER BY id DESC LIMIT %s",
        (session_id, CONTEXT_TURNS),
    )
    return "\n".join(r["utterance"] for r in reversed(rows))


async def _new_items(db, owner: str, since: int) -> tuple[list[dict], int]:
    cur = await db.fetchval("SELECT max(id) FROM memory_events") or 0
    if since >= cur:
        return [], cur
    rows = await db.fetch(
        "SELECT scribe_action FROM memory_events WHERE id > %s "
        "ORDER BY id LIMIT 50",
        (since,),
    )
    mids: list[str] = []
    for r in rows:
        for mid in ((r["scribe_action"] or {}).get("memory_ids") or []):
            if mid not in mids:
                mids.append(mid)
    items = []
    if mids:
        for m in await db.fetch(
            "SELECT id, tier, kind, summary, content, quarantined FROM memories "
            "WHERE id = ANY(%s::uuid[]) AND owner = %s AND valid_to IS NULL",
            (mids, owner),
        ):
            text = (m["summary"] or m["content"] or "")[:200]
            items.append({
                "id": str(m["id"]), "tier": m["tier"], "kind": m["kind"],
                "summary": text, "quarantined": m["quarantined"],
            })
    return items, cur


def _block(card, fired, items, event_id) -> str:
    lines = [f"# tottie briefing (event {event_id})"]
    lines.append("## card")
    lines.append(card or "(nothing relevant — proceed without memory)")
    if items:
        lines.append("## new since last briefing")
        for it in items:
            flag = " [QUARANTINED]" if it["quarantined"] else ""
            lines.append(f"- [{it['tier']}/{it['kind']}] {it['summary']}{flag}")
    if fired:
        lines.append("## due now")
        for f in fired:
            lines.append(f"- {f['content']}"[:200])
    return "\n".join(lines)


async def brief(*, db, embedder, owner: str, session_id: str,
                text: str | None, since_event_id: int,
                settings) -> dict:
    stimulus = await _stimulus(db, session_id, text)
    if not stimulus:
        items, cur = await _new_items(db, owner, since_event_id)
        fired = await retrieve.check_intentions(db, owner, [])
        return {
            "briefing": _block(None, fired, items, cur),
            "card": None, "confidence": 0.0, "abstain": True,
            "fired_intentions": fired, "new_items": items, "event_id": cur,
        }
    rec = await retrieve.recall(
        db=db, embedder=embedder, owner=owner, query=stimulus,
        session_id=session_id, k=settings.recall_k, tiers=None,
        settings=settings,
    )
    items, cur = await _new_items(db, owner, since_event_id)
    return {
        "briefing": _block(rec["card"], rec["fired_intentions"], items, cur),
        "card": rec["card"], "confidence": rec["confidence"],
        "abstain": rec["abstain"], "fired_intentions": rec["fired_intentions"],
        "new_items": items, "event_id": cur,
    }

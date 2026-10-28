"""Shared memory ops for the HTTP routes and the MCP server. Transport-neutral
errors (MemoryNotFound / NotOwner); each surface maps them to its own shape."""
from psycopg.types.json import Json

from . import retrieve


class MemoryNotFound(LookupError):
    pass


class NotOwner(PermissionError):
    pass


async def get_identity(db, owner: str, limit: int = 20) -> list[dict]:
    rows = await db.fetch(
        "SELECT id, kind, content, tags, salience FROM memories "
        "WHERE owner = %s AND tier = 'identity' AND valid_to IS NULL "
        "AND NOT quarantined ORDER BY salience DESC LIMIT %s",
        (owner, limit),
    )
    return [{**r, "id": str(r["id"])} for r in rows]


async def probe_room(db, owner: str, tag: str, limit: int = 20) -> list[dict]:
    rows = await db.fetch(
        "SELECT id, tier, kind, content, tags, salience FROM memories "
        "WHERE owner = %s AND valid_to IS NULL AND NOT quarantined "
        "AND %s = ANY(tags) ORDER BY salience DESC, utility DESC LIMIT %s",
        (owner, tag.lstrip("#"), limit),
    )
    return [{**r, "id": str(r["id"])} for r in rows]


async def confirm_memory(db, memory_id: str, owner: str) -> dict:
    row = await db.fetchrow(
        "SELECT id, owner, quarantined, source FROM memories WHERE id = %s::uuid",
        (memory_id,),
    )
    if row is None:
        raise MemoryNotFound("unknown memory id")
    if row["owner"] != owner:
        raise NotOwner("not your memory")
    if not row["quarantined"]:
        return {"id": memory_id, "quarantined": False, "already": True}
    await db.execute(
        "UPDATE memories SET quarantined = false, trust = 'user_direct' "
        "WHERE id = %s::uuid",
        (memory_id,),
    )
    await db.execute(
        "INSERT INTO memory_events (session_id, utterance, observer_verdict, "
        "scribe_action) VALUES (%s, %s, %s, %s)",
        (
            (row["source"] or {}).get("session"),
            f"[confirm] {memory_id}",
            Json({"recall": False, "confirm": True}),
            Json({"op": "CONFIRM", "memory_ids": [memory_id]}),
        ),
    )
    return {"id": memory_id, "quarantined": False}


async def forget_memory(db, *, owner: str, id: str | None = None,
                        query: str | None = None, embedder=None,
                        settings=None) -> dict:
    if id is not None:
        row = await db.fetchrow(
            "SELECT id, owner, source FROM memories WHERE id = %s::uuid",
            (id,),
        )
        if row is None or row["owner"] != owner:
            raise MemoryNotFound("nothing to forget")
        targets = [(str(row["id"]), (row["source"] or {}).get("session"))]
        by = "id"
    else:
        assert query and query.strip(), "id or query required"
        out = await retrieve.recall(
            db=db, embedder=embedder, owner=owner, query=query.strip(),
            session_id="forget", k=1, tiers=None, settings=settings,
        )
        if out["abstain"] or not out["hits"]:
            raise MemoryNotFound(
                "no confident match; refusing to delete by vague query")
        targets = [(out["hits"][0]["id"], None)]
        by = "query"
    forgot = [t[0] for t in targets]
    await db.execute(
        "DELETE FROM memory_links WHERE owner = %s AND "
        "(src = ANY(%s::uuid[]) OR dst = ANY(%s::uuid[]))",
        (owner, forgot, forgot),
    )
    await db.execute(
        "DELETE FROM memories WHERE owner = %s AND id = ANY(%s::uuid[])",
        (owner, forgot),
    )
    pruned = await db.fetch(
        "DELETE FROM memory_events "
        "WHERE (scribe_action->'memory_ids')::jsonb @> %s::jsonb RETURNING id",
        (Json(forgot),),
    )
    await db.execute(
        "INSERT INTO memory_events (session_id, utterance, observer_verdict, "
        "scribe_action) VALUES (%s, %s, %s, %s)",
        (
            targets[0][1],
            f"[forget] {len(forgot)} rows",
            Json({"recall": False, "forget": True}),
            Json({"op": "FORGET", "forgot_ids": forgot,
                  "events_pruned": len(pruned), "by": by}),
        ),
    )
    return {"forgot_ids": forgot, "events_pruned": len(pruned)}

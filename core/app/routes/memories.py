"""POST /memories/{id}/confirm — release a quarantined row into the active set.
POST /forget — true delete (right-to-be-forgotten) + audit row.

Confirm is owner-only: the requesting owner must own the row. Forget prunes
the rows, their links, and the write events that created them, then appends
a FORGET audit event (which carries ids, never content).
"""
from fastapi import APIRouter, HTTPException, Request, status
from psycopg.types.json import Json
from pydantic import BaseModel, Field

from ..agents import retrieve

router = APIRouter()


class ConfirmRequest(BaseModel):
    owner: str = Field(min_length=1)


class ForgetRequest(BaseModel):
    owner: str = Field(min_length=1)
    id: str | None = None
    query: str | None = None
    k: int = Field(default=3, ge=1, le=10)


@router.post("/memories/{memory_id}/confirm")
async def post_confirm(memory_id: str, body: ConfirmRequest, request: Request) -> dict:
    db = request.app.state.db
    row = await db.fetchrow(
        "SELECT id, owner, quarantined, source FROM memories WHERE id = %s::uuid",
        (memory_id,),
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown memory id")
    if row["owner"] != body.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your memory")
    if not row["quarantined"]:
        return {"id": memory_id, "quarantined": False, "already": True}
    await db.execute(
        "UPDATE memories SET quarantined = false, trust = 'user_direct' "
        "WHERE id = %s::uuid",
        (memory_id,),
    )
    session = (row["source"] or {}).get("session")
    await db.execute(
        "INSERT INTO memory_events (session_id, utterance, observer_verdict, "
        "scribe_action) VALUES (%s, %s, %s, %s)",
        (
            session,
            f"[confirm] {memory_id}",
            Json({"recall": False, "confirm": True}),
            Json({"op": "CONFIRM", "memory_ids": [memory_id]}),
        ),
    )
    return {"id": memory_id, "quarantined": False}


@router.post("/forget")
async def post_forget(body: ForgetRequest, request: Request) -> dict:
    if not body.id and not (body.query or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "id or query required"
        )
    db = request.app.state.db
    if body.id:
        row = await db.fetchrow(
            "SELECT id, owner, source FROM memories WHERE id = %s::uuid",
            (body.id,),
        )
        if row is None or row["owner"] != body.owner:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "nothing to forget")
        targets = [(str(row["id"]), (row["source"] or {}).get("session"))]
    else:
        if request.app.state.embedder is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {"error": "embedder unavailable", "retryable": True},
            )
        out = await retrieve.recall(
            db=db, embedder=request.app.state.embedder, owner=body.owner,
            query=body.query.strip(), session_id="forget", k=1,
            tiers=None, settings=request.app.state.settings,
        )
        if out["abstain"] or not out["hits"]:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "no confident match; refusing to delete by vague query",
            )
        targets = [(out["hits"][0]["id"], None)]
    forgot = [t[0] for t in targets]
    await db.execute(
        "DELETE FROM memory_links WHERE owner = %s AND "
        "(src = ANY(%s::uuid[]) OR dst = ANY(%s::uuid[]))",
        (body.owner, forgot, forgot),
    )
    await db.execute(
        "DELETE FROM memories WHERE owner = %s AND id = ANY(%s::uuid[])",
        (body.owner, forgot),
    )
    # Overlap-only (no session filter): ids are globally unique, and a
    # query-forget has no session — filtering by it would leak utterances.
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
                  "events_pruned": len(pruned), "by": "id" if body.id else "query"}),
        ),
    )
    return {"forgot_ids": forgot, "events_pruned": len(pruned)}

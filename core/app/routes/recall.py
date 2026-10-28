"""POST /recall — cue-typed associative recall + Context Card.

GET /identity — the ambient identity slice (what the card header shows).
GET /probe — the deliberate probe: a tag room's live, non-quarantined rows.
Auth is wired in main.py (router-level dependency), same as /write.
"""
from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ..agents import memories, retrieve

router = APIRouter()

TIERS = {"identity", "episodic", "knowledge", "procedural"}


class RecallRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(min_length=1, max_length=128)
    owner: str | None = None
    tiers: list[str] | None = None
    k: int | None = Field(default=None, ge=1, le=32)


@router.post("/recall")
async def post_recall(body: RecallRequest, request: Request) -> dict:
    query = body.query.strip()
    if not query:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "query must not be blank"
        )
    if body.tiers is not None:
        bad = [t for t in body.tiers if t not in TIERS]
        if bad:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"unknown tiers {bad}; want subset of {sorted(TIERS)}",
            )
    settings = request.app.state.settings
    if request.app.state.embedder is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"error": "embedder unavailable", "retryable": True},
        )
    return await retrieve.recall(
        db=request.app.state.db,
        embedder=request.app.state.embedder,
        owner=body.owner or settings.owner,
        query=query,
        session_id=body.session_id,
        k=body.k or settings.recall_k,
        tiers=body.tiers,
        settings=settings,
    )


@router.get("/identity")
async def get_identity(
    request: Request, owner: str = Query(""), limit: int = Query(20, ge=1, le=100)
) -> dict:
    settings = request.app.state.settings
    rows = await memories.get_identity(
        request.app.state.db, owner or settings.owner, limit
    )
    return {"owner": owner or settings.owner, "identity": rows}


@router.get("/probe")
async def get_probe(
    request: Request,
    tag: str = Query(...),
    owner: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    settings = request.app.state.settings
    rows = await memories.probe_room(
        request.app.state.db, owner or settings.owner, tag, limit
    )
    return {"tag": tag, "owner": owner or settings.owner, "memories": rows}

"""POST /consolidate — run the Sleep job on demand.

Replay -> semanticise -> rank -> decay; returns the summary the Panel
prints ("N episodic -> M semantic; K ranked out"). Sleep degrades, never
dies: if the LLM semanticise step fails, rank + decay still run and the
summary carries semantic_error. Auth is wired in main.py.
"""
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..agents import consolidate

router = APIRouter()


class ConsolidateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    owner: str | None = None


@router.post("/consolidate")
async def post_consolidate(body: ConsolidateRequest, request: Request) -> dict:
    settings = request.app.state.settings
    if request.app.state.embedder is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"error": "embedder unavailable", "retryable": True},
        )
    return await consolidate.consolidate(
        db=request.app.state.db, embedder=request.app.state.embedder,
        owner=body.owner or settings.owner, session_id=body.session_id,
        settings=settings,
    )

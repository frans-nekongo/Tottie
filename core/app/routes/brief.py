"""POST /briefing — one call per agent turn: ambient memory surface.

Body: {session_id, agent_id, owner?, text?, since_event_id?}. No text:
brief on the session's own recent utterances. Returns the card, fired
intentions, items formed since the cursor, and a pre-formatted `briefing`
block. Paired agents only (pairing.require_paired_http); unknown ids are
left visible for the owner to pair. Auth wired in main.py.
"""
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..agents import brief as brain
from ..agents import pairing

router = APIRouter()


class BriefRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    owner: str | None = None
    text: str | None = Field(default=None, max_length=4000)
    since_event_id: int = Field(default=0, ge=0)


@router.post("/briefing")
async def post_briefing(body: BriefRequest, request: Request) -> dict:
    settings = request.app.state.settings
    if request.app.state.embedder is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"error": "embedder unavailable", "retryable": True},
        )
    owner = body.owner or settings.owner
    await pairing.require_paired_http(
        request.app.state.db, owner, body.agent_id, transport="http",
        session_id=body.session_id,
    )
    return await brain.brief(
        db=request.app.state.db, embedder=request.app.state.embedder,
        owner=owner, session_id=body.session_id,
        text=body.text, since_event_id=body.since_event_id, settings=settings,
    )

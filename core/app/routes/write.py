"""POST /write — enqueue a turn for curation. 202 immediately, never wait for the model.

Auth is wired in main.py (router-level dependency). With no embedder the route
503s (spec: unhealthy embedder is visible, never silent).
"""
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..agents import observer, scribe
from ..queue import WorkerTurn

router = APIRouter()

TRUSTS = {"user_direct", "tool", "web", "model_inferred"}


class Source(BaseModel):
    trust: str = "user_direct"
    origin: str | None = None


class WriteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    session_id: str = Field(min_length=1, max_length=128)
    turn: int = Field(ge=0)
    owner: str | None = None
    source: Source = Source()


@router.post("/write", status_code=202)
async def post_write(body: WriteRequest, request: Request) -> dict:
    if body.source.trust not in TRUSTS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"trust must be one of {sorted(TRUSTS)}",
        )
    text = body.text.strip()
    if not text:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "text must not be blank"
        )
    settings = request.app.state.settings
    if request.app.state.embedder is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"error": "embedder unavailable", "retryable": True},
        )
    turn = WorkerTurn(
        text=text,
        session_id=body.session_id,
        turn=body.turn,
        owner=body.owner or settings.owner,
        trust=body.source.trust,
        origin=body.source.origin,
    )
    if settings.inline_write:
        turn = WorkerTurn(
            text=turn.text, session_id=turn.session_id, turn=turn.turn,
            owner=turn.owner, trust=turn.trust, origin=turn.origin,
            client_event_id=uuid.uuid4().hex,
        )
        obs = await observer.observe(
            db=request.app.state.db, embedder=request.app.state.embedder,
            turn=turn, settings=settings,
        )
        await scribe.persist(
            db=request.app.state.db, embedder=request.app.state.embedder,
            turn=turn, obs=obs,
        )
        return {"event_id": turn.client_event_id, "mode": "inline"}
    eid = request.app.state.queue.enqueue_nowait(turn)
    return {"event_id": eid, "mode": "queued"}

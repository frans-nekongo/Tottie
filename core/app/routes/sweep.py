"""POST /sweep — run the Updater on demand.

Merges near-dup pairs and retires NLI-caught contradictions newest-wins.
Queue mode (202): the sweep runs on the job queue; this route enqueues.
Inline mode: the worker pool never starts (main.py), so an enqueued sweep
would sit forever — a 202 that lies. The route awaits the sweep directly
instead (mirrors /write), returning the summary with mode "inline".
Auth is wired in main.py.
"""
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..agents import updater
from ..queue import UPDATE_SWEEP

router = APIRouter()


class SweepRequest(BaseModel):
    owner: str | None = None


@router.post("/sweep", status_code=202)
async def post_sweep(body: SweepRequest, request: Request) -> dict:
    settings = request.app.state.settings
    if request.app.state.embedder is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"error": "embedder unavailable", "retryable": True},
        )
    if settings.inline_write:
        summary = await updater.run_sweep(
            db=request.app.state.db, embedder=request.app.state.embedder,
            settings=settings, owner=body.owner or settings.owner,
        )
        return {"event_id": uuid.uuid4().hex, "mode": "inline",
                "summary": summary}
    eid = request.app.state.queue.enqueue_job(
        UPDATE_SWEEP, payload={"owner": body.owner or settings.owner})
    return {"event_id": eid, "mode": "queued"}

"""POST /sweep — run the Updater on demand (202, background job).

Merges near-dup pairs and retires NLI-caught contradictions newest-wins.
The sweep itself runs on the job queue; this route only enqueues.
Auth is wired in main.py.
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..queue import UPDATE_SWEEP

router = APIRouter()


class SweepRequest(BaseModel):
    owner: str | None = None


@router.post("/sweep", status_code=202)
async def post_sweep(body: SweepRequest, request: Request) -> dict:
    settings = request.app.state.settings
    eid = request.app.state.queue.enqueue_job(
        UPDATE_SWEEP, payload={"owner": body.owner or settings.owner})
    return {"event_id": eid, "mode": "queued"}

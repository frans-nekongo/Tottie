"""POST /memories/{id}/confirm — release a quarantined row into the active set.
POST /forget — true delete (right-to-be-forgotten) + audit row.

Thin HTTP mapping over agents.memories (shared with the MCP server).
"""
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..agents import memories
from ..agents.memories import MemoryNotFound, NotOwner

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
    try:
        return await memories.confirm_memory(
            request.app.state.db, memory_id, body.owner
        )
    except MemoryNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except NotOwner as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e


@router.post("/forget")
async def post_forget(body: ForgetRequest, request: Request) -> dict:
    if not body.id and not (body.query or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "id or query required"
        )
    if body.query and request.app.state.embedder is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"error": "embedder unavailable", "retryable": True},
        )
    try:
        return await memories.forget_memory(
            request.app.state.db, owner=body.owner, id=body.id,
            query=(body.query or "").strip() or None,
            embedder=request.app.state.embedder,
            settings=request.app.state.settings,
        )
    except MemoryNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e

"""Agent registry: bluetooth pairing for memory injection.

Agents register + heartbeat so the owner SEES them (id, label,
transport, online by fresh heartbeat). The owner pairs chosen ones
(UI toggle / CLI); injection (`tottie run --agent`) serves paired
agents only — tottie never pushes context where it was not invited.
Agents cannot self-pair: pairing is the owner's accept click.
Auth is wired in main.py.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()

ONLINE_TTL_S = 300


class RegisterRequest(BaseModel):
    owner: str | None = None
    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=256)
    transport: str = Field(default="cli", max_length=32)
    session_id: str | None = None


class IdRequest(BaseModel):
    owner: str | None = None
    id: str = Field(min_length=1, max_length=128)


def _owner(body_owner, settings):
    return body_owner or settings.owner


@router.post("/agents/register")
async def post_register(body: RegisterRequest, request: Request) -> dict:
    db = request.app.state.db
    owner = _owner(body.owner, request.app.state.settings)
    row = await db.execute_returning(
        "INSERT INTO agents (id, owner, label, transport, session_id) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET label = EXCLUDED.label, "
        "transport = EXCLUDED.transport, session_id = EXCLUDED.session_id, "
        "last_seen = now() RETURNING connected",
        (body.id, owner, body.label, body.transport, body.session_id),
    )
    return {"id": body.id, "connected": row["connected"]}


@router.post("/agents/heartbeat")
async def post_heartbeat(body: IdRequest, request: Request) -> dict:
    db = request.app.state.db
    owner = _owner(body.owner, request.app.state.settings)
    row = await db.execute_returning(
        "INSERT INTO agents (id, owner, label) VALUES (%s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET last_seen = now() "
        "RETURNING connected",
        (body.id, owner, body.id),
    )
    return {"id": body.id, "connected": row["connected"]}


@router.get("/agents")
async def get_agents(request: Request, owner: str | None = None) -> dict:
    db = request.app.state.db
    rows = await db.fetch(
        "SELECT id, label, transport, session_id, connected, last_seen, "
        "EXTRACT(EPOCH FROM (now() - last_seen)) < %s AS online "
        "FROM agents WHERE owner = %s ORDER BY last_seen DESC",
        (ONLINE_TTL_S, _owner(owner, request.app.state.settings)),
    )
    return {"agents": [
        {"id": r["id"], "label": r["label"], "transport": r["transport"],
         "session_id": r["session_id"], "connected": r["connected"],
         "online": r["online"],
         "last_seen": r["last_seen"].isoformat()} for r in rows]}


@router.post("/agents/pair")
async def post_pair(body: IdRequest, request: Request) -> dict:
    db = request.app.state.db
    row = await db.execute_returning(
        "UPDATE agents SET connected = true WHERE id = %s AND owner = %s "
        "RETURNING id",
        (body.id, _owner(body.owner, request.app.state.settings)),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="unknown agent")
    return {"id": body.id, "connected": True}


@router.post("/agents/unpair")
async def post_unpair(body: IdRequest, request: Request) -> dict:
    db = request.app.state.db
    row = await db.execute_returning(
        "UPDATE agents SET connected = false WHERE id = %s AND owner = %s "
        "RETURNING id",
        (body.id, _owner(body.owner, request.app.state.settings)),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="unknown agent")
    return {"id": body.id, "connected": False}

"""Paired-only injection: the bluetooth rule in one place.

Reads (brief/recall/probe/identity/chat-memory) serve PAIRED agents only.
Writes (remember/write/intend/sleep/confirm/forget) stay open — quarantine,
not pairing, judges incoming data.

Every check ALSO records presence: an unknown agent id auto-registers as a
visible (unpaired) row so the owner SEES who asked in the Agents tab, then
the read is refused with a pair-me error. No silent rows, no silent bypass.
"""
from fastapi import HTTPException, status


def pair_me_error(agent_id: str) -> dict:
    return {
        "error": "not_paired",
        "agent_id": agent_id,
        "message": (
            f"agent '{agent_id}' is visible but not paired: the owner "
            f"pairs it in the Agents tab first, then reads are served"
        ),
    }


async def presence(db, owner: str, agent_id: str, *, label: str | None = None,
                   transport: str, session_id: str | None = None) -> dict:
    """Upsert a visible row + fresh last_seen. Explicit register owns
    label/transport/session; presence only refreshes liveness (plus a
    session when one is given). Returns the row's {connected}."""
    row = await db.execute_returning(
        "INSERT INTO agents (id, owner, label, transport, session_id) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET last_seen = now(), "
        "session_id = COALESCE(EXCLUDED.session_id, agents.session_id) "
        "RETURNING connected, owner",
        (agent_id, owner, label or agent_id, transport, session_id),
    )
    return {"connected": row["connected"], "owner": row["owner"]}


async def check_paired(db, owner: str, agent_id: str, *, transport: str,
                       session_id: str | None = None) -> dict | None:
    """Presence + pairing check. None = paired, serve. Dict = refuse with
    this error (unknown ids are left visible for the owner to pair)."""
    row = await presence(db, owner, agent_id, transport=transport,
                         session_id=session_id)
    if row["owner"] != owner or not row["connected"]:
        return pair_me_error(agent_id)
    return None


async def require_paired_http(db, owner: str, agent_id: str, *,
                              transport: str,
                              session_id: str | None = None) -> None:
    """HTTP shape of check_paired: 403 with the pair-me error."""
    err = await check_paired(db, owner, agent_id, transport=transport,
                             session_id=session_id)
    if err is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, err)

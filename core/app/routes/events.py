"""GET /events — SSE stream of memory_events with resume.

Auth rides a ?token= query param: EventSource cannot set headers (spec).
Live tail is a 500ms poll — honest and plenty at demo scale.
Row shape follows schema.sql: utterance + JSONB verdict/action + latency/tokens.
"""
import asyncio
import hmac
import json

from fastapi import APIRouter, HTTPException, Query, Request, status
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

router = APIRouter()


@router.get("/events")
async def get_events(
    request: Request,
    session_id: str = Query(""),
    last_event_id: int = Query(0),
    token: str = Query(""),
    owner: str = Query(""),
):
    settings = request.app.state.settings
    if not settings.api_token or not hmac.compare_digest(token, settings.api_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad or missing token")
    db = request.app.state.db
    who = owner or settings.owner
    # Owner-wide watch: empty session streams every session of the owner
    # (the observatory). A session still narrows when given (old behavior).
    filt = "owner = %s AND id > %s"
    params: tuple = (who, last_event_id)
    if session_id:
        filt = "owner = %s AND session_id = %s AND id > %s"
        params = (who, session_id, last_event_id)

    async def gen():
        last = params[-1]
        while True:
            if await request.is_disconnected():
                break
            rows = await db.fetch(
                "SELECT id, ts, turn, utterance, observer_verdict, scribe_action, "
                "cue, latency_ms, tokens FROM memory_events "
                f"WHERE {filt} "
                "ORDER BY id LIMIT 100",
                params[:-1] + (last,),
            )
            for r in rows:
                last = r["id"]
                yield ServerSentEvent(
                    id=str(last),
                    event="memory",
                    data=json.dumps(
                        {
                            "id": r["id"],
                            "ts": r["ts"],
                            "turn": r["turn"],
                            "utterance": r["utterance"],
                            "verdict": r["observer_verdict"],
                            "action": r["scribe_action"],
                            "cue": r["cue"],
                            "latency_ms": r["latency_ms"],
                            "tokens": r["tokens"],
                        },
                        default=str,
                    ),
                )
            await asyncio.sleep(0.5)

    return EventSourceResponse(gen(), ping=15)

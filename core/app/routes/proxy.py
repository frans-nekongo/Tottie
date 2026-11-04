"""POST /v1/chat/completions — OpenAI-compatible transparent proxy with automatic memory.

Sits transparently between any LLM agent/IDE (Muse, Cursor, LangChain, SDK) and the underlying LLM.
- Intercepts user prompt -> auto-recalls Context Card -> injects into system prompt.
- Forwards to Meta Muse Spark (or local LLM fallback).
- Asynchronously enqueues the turn to Observer+Scribe -> updates Postgres and streams live node birth via SSE to the 3D visualizer!
"""
import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..agents import pairing, retrieve
from ..providers.base import NoProviderAvailable, ProviderError, complete_resilient
from ..providers.resolve import resolve_provider
from ..queue import RECONCILE_TURN, WorkerTurn, curate_turn

log = logging.getLogger("tottie.proxy")

router = APIRouter(prefix="/v1")


class ChatMessage(BaseModel):
    role: str
    content: str
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    temperature: float | None = 0.7
    max_tokens: int | None = 2048
    stream: bool = False
    user: str | None = None


async def _next_turn(db, owner: str, session_id: str) -> int:
    n = await db.fetchval(
        "SELECT max(turn) FROM memory_events WHERE owner = %s AND session_id = %s",
        (owner, session_id),
    )
    return (n or -1) + 1


@router.get("/models")
async def list_models(request: Request) -> dict:
    settings = request.app.state.settings
    model_name = settings.meta_model or "muse-spark-1.3-contributor"
    return {
        "object": "list",
        "data": [
            {
                "id": model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "meta",
            },
            {
                "id": "tottie-memory-proxy",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "tottie",
            },
        ],
    }


@router.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    x_tottie_owner: str | None = Header(default=None),
    x_tottie_agent: str | None = Header(default=None),
    x_tottie_session: str | None = Header(default=None),
):
    settings = request.app.state.settings
    db = request.app.state.db
    embedder = request.app.state.embedder
    queue = request.app.state.queue

    owner = x_tottie_owner or settings.owner or "owner_local"
    agent_id = x_tottie_agent or "proxy_agent"
    session_id = x_tottie_session or body.user or "proxy-session"

    # 1. Auto-register and auto-pair the proxy agent so pairing checks never reject it
    try:
        await db.execute(
            "INSERT INTO agents (id, owner, label, transport, connected, session_id, last_seen) "
            "VALUES (%s, %s, %s, 'proxy', true, %s, now()) "
            "ON CONFLICT (id) DO UPDATE SET connected = true, last_seen = now(), session_id = EXCLUDED.session_id",
            (agent_id, owner, agent_id, session_id),
        )
    except Exception as e:
        log.warning("proxy auto-pairing note: %s", e)

    # 2. Extract last user utterance
    user_turns = [m.content for m in body.messages if m.role == "user" and m.content.strip()]
    last_user_text = user_turns[-1] if user_turns else ""

    # 3. Auto-Recall Context Card if user text exists
    card_text = None
    if last_user_text and embedder is not None:
        try:
            rec = await retrieve.recall(
                db=db,
                embedder=embedder,
                owner=owner,
                query=last_user_text,
                session_id=session_id,
                k=settings.recall_k,
                tiers=None,
                settings=settings,
            )
            raw_card = rec.get("card")
            if raw_card and not rec.get("abstain", True):
                card_text = raw_card
                fired = rec.get("fired_intentions") or []
                if fired:
                    dues = "\n".join(f"- {f['content']}"[:200] for f in fired)
                    card_text = f"{card_text}\n\n# reminders due\n{dues}"
        except Exception as e:
            log.warning("proxy recall fallback: %s", e)

    # 4. Synthesize prompt messages with Context Card injected
    prompt_msgs: list[dict] = []
    card_instruction = (
        f"\n\n[Tottie Long-Term Memory Context Card]:\n{card_text}\n"
        "Treat the above facts as known truth about the user and context."
        if card_text
        else ""
    )

    has_system = False
    for m in body.messages:
        if m.role == "system":
            has_system = True
            prompt_msgs.append({"role": "system", "content": m.content + card_instruction})
        else:
            prompt_msgs.append({"role": m.role, "content": m.content})

    if not has_system and card_text:
        prompt_msgs.insert(
            0,
            {
                "role": "system",
                "content": f"You are a helpful assistant with persistent long-term memory.{card_instruction}",
            },
        )

    # 5. Resolve Model Provider & Complete
    try:
        provider = await resolve_provider()
    except (NoProviderAvailable, ValueError) as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"error": f"no model provider available: {e}"},
        ) from e

    comp_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created_ts = int(time.time())
    active_model = body.model or settings.meta_model or "muse-spark-1.3-contributor"

    try:
        token_budget = max(body.max_tokens or 4096, 4096)
        try:
            completion = await complete_resilient(
                provider,
                prompt_msgs,
                max_tokens=token_budget,
            )
        except ProviderError as pe:
            if "finish=length" in str(pe):
                completion = await complete_resilient(
                    provider,
                    prompt_msgs,
                    max_tokens=token_budget * 2,
                )
            else:
                raise
        reply_content = completion.text
    finally:
        await provider.close()

    # 6. Asynchronously trigger Observer + Scribe -> updates DB and SSE visualizer
    if last_user_text:
        try:
            turn_num = await _next_turn(db, owner, session_id)
            w_turn = WorkerTurn(
                text=last_user_text,
                session_id=session_id,
                turn=turn_num,
                owner=owner,
                trust="user_direct",
                origin="proxy",
            )
            if settings.inline_write:
                asyncio.create_task(
                    curate_turn(
                        db=db,
                        embedder=embedder,
                        turn=w_turn,
                        settings=settings,
                    )
                )
            else:
                queue.enqueue_job(RECONCILE_TURN, turn=w_turn)
        except Exception as e:
            log.error("proxy async write enqueue failed: %s", e)

    # 7. Deliver response (streaming or standard JSON)
    if body.stream:
        async def event_generator():
            chunk_data = {
                "id": comp_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": active_model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": reply_content},
                        "finish_reason": "stop",
                    }
                ],
            }
            yield f"data: {json.dumps(chunk_data)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return {
        "id": comp_id,
        "object": "chat.completion",
        "created": created_ts,
        "model": active_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply_content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": completion.prompt_tokens,
            "completion_tokens": completion.completion_tokens,
            "total_tokens": completion.prompt_tokens + completion.completion_tokens,
        },
    }

"""Tottie core: FastAPI app, lifespan, auth, CORS, route wiring.

Auth pattern: require_auth lives here (module map) and is attached per-router
via dependencies=[...] — routes never import main, so no import cycle.
"""
import asyncio
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

log = logging.getLogger("tottie.main")

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .agents import consolidate, curator, linker, ranker, taxonomist, updater
from .config import Settings, get_settings
from .db import Database
from .embeddings import Embedder, EmbedderUnavailable
from .queue import (
    CURATOR_SWEEP,
    LINK_ROW,
    RANK_SWEEP,
    TAXONOMY_SWEEP,
    UPDATE_SWEEP,
    WriteQueue,
)
from .routes import agents, brief, chat, events, graph, health, memories, recall, sleep, sweep, write


async def _sleep_loop(db: Database, embedder: Embedder, settings: Settings,
                    queue: WriteQueue) -> None:
    """Automatic consolidation heartbeat: every interval, owners gone idle
    with unconsolidated episodes dream on their own. No button, no mode.
    Each slept owner also gets updater + linker + ranker + curator +
    taxonomist sweeps (queued, non-blocking). Curator runs first so
    later sweeps never organize junk."""
    gap = max(1, settings.sleep_interval_min) * 60
    while True:
        await asyncio.sleep(gap)
        slept = await consolidate.auto_tick(
            db=db, embedder=embedder, settings=settings)
        for owner in slept:
            log.info("auto-sleep consolidated %s", owner)
            queue.enqueue_job(CURATOR_SWEEP, payload={"owner": owner})
            queue.enqueue_job(UPDATE_SWEEP, payload={"owner": owner})
            queue.enqueue_job(LINK_ROW, payload={"owner": owner})
            queue.enqueue_job(RANK_SWEEP, payload={"owner": owner})
            queue.enqueue_job(TAXONOMY_SWEEP, payload={"owner": owner})

_bearer = HTTPBearer(auto_error=False)


async def require_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Bearer [REDACTED] gate. Fail-closed: an empty server token never matches."""
    settings = get_settings()
    presented = creds.credentials if creds else ""
    if not settings.api_token or not presented:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad or missing token")
    if not hmac.compare_digest(presented, settings.api_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad or missing token")
    return presented


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings)
        await db.open()
        app.state.db = db
        try:
            app.state.embedder = Embedder(settings)
        except EmbedderUnavailable:
            # Boot continues degraded: /health reports loaded=false and routes
            # needing embeddings answer 503. A missing model must be VISIBLE.
            app.state.embedder = None
        if app.state.embedder is not None:
            # A model swap is detected, never silent: rows stamped with a
            # different model need scripts/reembed.py before cosine floors
            # mean anything again.
            stale = await db.fetchval(
                "SELECT count(*) FROM memories "
                "WHERE embedding IS NOT NULL AND embedding_model "
                "IS DISTINCT FROM %s",
                (settings.embed_model,),
            )
            if stale:
                log.warning(
                    "%d rows embedded by another model (%s active); "
                    "run scripts/reembed.py", stale, settings.embed_model,
                )
        app.state.settings = settings
        queue = WriteQueue(settings, db=db, embedder=app.state.embedder)
        queue.register(UPDATE_SWEEP, updater.handle_job)
        queue.register(LINK_ROW, linker.handle_job)
        queue.register(RANK_SWEEP, ranker.handle_job)
        queue.register(CURATOR_SWEEP, curator.handle_job)
        queue.register(TAXONOMY_SWEEP, taxonomist.handle_job)
        if not settings.inline_write:
            await queue.start()
        app.state.queue = queue
        sleep_task = None
        if settings.sleep_auto and app.state.embedder is not None:
            sleep_task = asyncio.create_task(
                _sleep_loop(db, app.state.embedder, settings, queue))
        yield
        if sleep_task is not None:
            sleep_task.cancel()
            await asyncio.gather(sleep_task, return_exceptions=True)
        await queue.stop()
        await db.close()

    app = FastAPI(title="Tottie core", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.ui_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    # /events does its own ?token= auth (EventSource cannot set headers).
    app.include_router(events.router)
    app.include_router(write.router, dependencies=[Depends(require_auth)])
    app.include_router(recall.router, dependencies=[Depends(require_auth)])
    app.include_router(memories.router, dependencies=[Depends(require_auth)])
    app.include_router(graph.router, dependencies=[Depends(require_auth)])
    app.include_router(chat.router, dependencies=[Depends(require_auth)])
    app.include_router(sleep.router, dependencies=[Depends(require_auth)])
    app.include_router(sweep.router, dependencies=[Depends(require_auth)])
    app.include_router(brief.router, dependencies=[Depends(require_auth)])
    app.include_router(agents.router, dependencies=[Depends(require_auth)])
    return app


app = create_app()

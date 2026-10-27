"""Tottie core: FastAPI app, lifespan, auth, CORS, route wiring."""
import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings
from .db import Database
from .embeddings import Embedder, EmbedderUnavailable
from .routes import health

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
        app.state.settings = settings
        yield
        await db.close()

    app = FastAPI(title="Tottie core", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.ui_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    return app


app = create_app()

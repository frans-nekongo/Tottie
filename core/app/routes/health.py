"""GET /health — the only unauthenticated route. Readiness gate for demo + harness."""
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def get_health(request: Request) -> dict:
    db = request.app.state.db
    embedder = request.app.state.embedder
    settings = request.app.state.settings
    try:
        stats = dict(db.pool.get_stats())
        pool_open = True
    except Exception:
        stats = {}
        pool_open = False
    loaded = embedder is not None
    from ..providers.resolve import resolve_provider

    try:
        provider = await resolve_provider()
        # Pinned modes skip the probe by design (fail loud at use); health
        # must not echo an unverified pin. Verify before reporting.
        active: str | None = (
            provider.name if await provider.healthy() else None
        )
        await provider.close()
    except Exception:
        active = None
    queue = getattr(request.app.state, "queue", None)
    return {
        "status": "ok" if (pool_open and loaded) else "degraded",
        "pool": {"open": pool_open, "stats": stats},
        "queue_depth": queue.depth if queue is not None else None,
        "embedder": {"loaded": loaded, "model": settings.embed_model},
        "providers": {
            "mode": (settings.provider or "auto").strip().lower(),
            "meta": {"configured": bool(settings.meta_api_key)},
            "local": {"configured": bool(settings.local_llm_url)},
            "active": active,
        },
    }

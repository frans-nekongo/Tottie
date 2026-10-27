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
    return {
        "status": "ok" if (pool_open and loaded) else "degraded",
        "pool": {"open": pool_open, "stats": stats},
        "queue_depth": None,  # W1 owns the write queue
        "embedder": {"loaded": loaded, "model": settings.embed_model},
        "providers": {
            "meta": {"configured": bool(settings.meta_api_key)},
            "local": {"configured": bool(settings.local_llm_url)},
        },
    }

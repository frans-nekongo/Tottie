"""GET /health without a token: pool open, real embedder loaded."""
import pytest

from app.config import get_settings


@pytest.mark.asyncio
async def test_health_reports_ready(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["embedder"]["loaded"] is True
    assert body["embedder"]["model"] == get_settings().embed_model
    assert body["pool"]["open"] is True

"""Dead provider -> RAW episodic row flagged needs_curation. Fast, deterministic:
connection refused, no LLM involved."""
import pytest

from app.agents import observer, scribe
from app.config import get_settings, Settings
from app.embeddings import Embedder
from app.queue import WorkerTurn


@pytest.mark.asyncio
async def test_raw_fallback_on_dead_provider(db, monkeypatch):
    monkeypatch.setenv("TOTTIE_PROVIDER", "meta")
    monkeypatch.setenv("META_BASE_URL", "http://127.0.0.1:9")  # dead port
    get_settings.cache_clear()
    from app.providers import resolve as resolve_mod

    resolve_mod._cache.clear()
    emb = Embedder(Settings())
    turn = WorkerTurn(
        text="Fallback fact: the test sky.",
        session_id="fb", turn=0, owner="fb",
        trust="user_direct", origin=None, client_event_id="e1",
    )
    obs = await observer.observe(
        db=db, embedder=emb, turn=turn, settings=get_settings()
    )
    assert obs.raw_fallback is True
    action = await scribe.persist(db=db, embedder=emb, turn=turn, obs=obs)
    assert action.startswith("RAW")
    row = await db.fetchrow(
        "SELECT needs_curation, tier FROM memories WHERE owner = 'fb'"
    )
    assert row["needs_curation"] is True
    assert row["tier"] == "episodic"

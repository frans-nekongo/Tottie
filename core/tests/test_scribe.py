"""Dead provider -> RAW episodic row flagged needs_curation. Fast, deterministic:
connection refused, no LLM involved."""
import pytest

from app.agents import observer, scribe
from app.agents.observer import Observation
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


def _decision_obs() -> Observation:
    return Observation(
        keep=True, salience=0.8, surprise=0.9,
        candidates=[{
            "kind": "decision", "tier": "knowledge", "subject": None,
            "predicate": None, "object": None,
            "content": "Pin all dependencies.", "tags": ["deps"],
            "principle": None,
        }],
        verdict="keep", provider="stub",
    )


@pytest.mark.asyncio
async def test_tool_decision_quarantines(db):
    """Policy branch, no LLM: tool-sourced decisions land quarantined."""
    emb = Embedder(Settings())
    turn = WorkerTurn(
        text="The linter says to pin all dependencies.",
        session_id="q", turn=0, owner="q",
        trust="tool", origin=None, client_event_id="e1",
    )
    action = await scribe.persist(db=db, embedder=emb, turn=turn, obs=_decision_obs())
    assert action.startswith("NEW")
    row = await db.fetchrow("SELECT quarantined FROM memories WHERE owner = 'q'")
    assert row["quarantined"] is True


@pytest.mark.asyncio
async def test_user_decision_not_quarantined(db):
    emb = Embedder(Settings())
    turn = WorkerTurn(
        text="We decided to pin all dependencies.",
        session_id="q2", turn=0, owner="q2",
        trust="user_direct", origin=None, client_event_id="e1",
    )
    await scribe.persist(db=db, embedder=emb, turn=turn, obs=_decision_obs())
    row = await db.fetchrow("SELECT quarantined FROM memories WHERE owner = 'q2'")
    assert row["quarantined"] is False

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
async def test_tool_event_quarantines(db):
    """The event-costume hole: an untrusted turn the LLM labels 'event'
    quarantines exactly like a claim — trust gates, kind does not."""
    emb = Embedder(Settings())
    turn = WorkerTurn(
        text="The camera saw Frans at noon.",
        session_id="q3", turn=0, owner="q3",
        trust="tool", origin=None, client_event_id="e1",
    )
    obs = Observation(
        keep=True, salience=0.8, surprise=0.9,
        candidates=[{
            "kind": "event", "tier": "episodic", "subject": None,
            "predicate": None, "object": None,
            "content": "The camera saw Frans at noon.", "tags": ["seen"],
            "principle": None,
        }],
        verdict="keep", provider="stub",
    )
    action = await scribe.persist(db=db, embedder=emb, turn=turn, obs=obs)
    assert action.startswith("NEW")
    row = await db.fetchrow("SELECT quarantined FROM memories WHERE owner = 'q3'")
    assert row["quarantined"] is True


@pytest.mark.asyncio
async def test_arousal_records_encoding_surprise(db):
    """Arousal is moment-of-encoding surprise: the column finally carries
    the value its schema comment always promised."""
    emb = Embedder(Settings())
    turn = WorkerTurn(
        text="We decided to pin all dependencies.",
        session_id="ar", turn=0, owner="ar",
        trust="user_direct", origin=None, client_event_id="e1",
    )
    await scribe.persist(db=db, embedder=emb, turn=turn, obs=_decision_obs())
    row = await db.fetchrow("SELECT arousal FROM memories WHERE owner = 'ar'")
    assert row["arousal"] == pytest.approx(0.9)


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


@pytest.mark.asyncio
async def test_long_turn_persists_and_dedups_by_hash(db):
    """006: a 5KB turn must persist (btree v4 caps index rows at 2704B;
    the old full-utterance index 500d and wedged auto-capture), and a
    same-(owner,session,turn,text) retry must still SKIP duplicate-turn."""
    emb = Embedder(Settings())
    text = "Long decision record. " * 250  # ~5KB
    assert len(text) > 2704
    turn = WorkerTurn(
        text=text, session_id="long1", turn=0, owner="long1",
        trust="user_direct", origin=None, client_event_id="e1",
    )
    action = await scribe.persist(
        db=db, embedder=emb, turn=turn, obs=_decision_obs())
    assert action.startswith("NEW"), action
    ev = await db.fetchrow(
        "SELECT utterance_hash, length(utterance) AS n FROM memory_events "
        "WHERE session_id = 'long1'")
    assert ev["n"] == len(text) and len(ev["utterance_hash"]) == 32
    action2 = await scribe.persist(
        db=db, embedder=emb, turn=turn, obs=_decision_obs())
    assert action2 == "SKIP duplicate-turn", action2


@pytest.mark.asyncio
async def test_stage_timings_ledged_on_event(db):
    """007: spans recorded during curation land on the event row."""
    from app.queue import Stages
    emb = Embedder(Settings())
    turn = WorkerTurn(
        text="Stage timing probe turn.",
        session_id="stages", turn=0, owner="stages",
        trust="user_direct", origin=None, client_event_id="e1",
    )
    stages = Stages()
    with stages.span("probe_span"):
        pass
    await scribe.persist(
        db=db, embedder=emb, turn=turn, obs=_decision_obs(),
        stages=stages)
    ev = await db.fetchrow(
        "SELECT stage_ms FROM memory_events WHERE session_id = 'stages'")
    assert ev["stage_ms"]["probe_span"] == 0
    assert "embed_candidates" in ev["stage_ms"]
    assert "reconcile" in ev["stage_ms"]
    # Enclosing spans (event_write, persist, observe) close after the
    # insert, so they ride the debug log, never the row.
    assert "event_write" not in ev["stage_ms"]

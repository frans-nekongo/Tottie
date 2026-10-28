"""Observer length-retry: first sample spirals (finish=length), resample lands.

The provider is scripted — a live model cannot be forced to spiral on
demand — but everything else is real: gates, embedder, Postgres. The stub
exercises the retry branch, not the model.
"""
import pytest

from app.agents import observer
from app.config import get_settings, Settings
from app.embeddings import Embedder
from app.providers.base import Completion, ProviderError
from app.queue import WorkerTurn


class SpiralOnce:
    name = "stub"

    def __init__(self) -> None:
        self.calls = 0

    async def healthy(self) -> bool:
        return True

    async def complete(self, messages, *, max_tokens=1024, json_object=False, reasoning_effort=None):
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("meta: empty content (finish=length)")
        return Completion(
            text='{"keep": true, "salience": 0.8, "candidates": ['
            '{"kind": "decision", "subject": null, "predicate": null, '
            '"object": null, "content": "Pin all dependencies.", '
            '"tags": ["deps"], "principle": null}]}',
            model="stub",
            prompt_tokens=10,
            completion_tokens=20,
        )

    async def close(self) -> None:
        pass


class SpiralAlways(SpiralOnce):
    async def complete(self, messages, *, max_tokens=1024, json_object=False, reasoning_effort=None):
        self.calls += 1
        raise ProviderError("meta: empty content (finish=length)")


def _turn():
    return WorkerTurn(
        text="The linter says to pin all dependencies.",
        session_id="retry", turn=0, owner="retry",
        trust="user_direct", origin=None, client_event_id="e1",
    )


@pytest.mark.asyncio
async def test_length_retry_resamples_once(db, monkeypatch):
    stub = SpiralOnce()

    async def fake_resolve():
        return stub

    monkeypatch.setattr(observer, "resolve_provider", fake_resolve)
    emb = Embedder(Settings())
    obs = await observer.observe(
        db=db, embedder=emb, turn=_turn(), settings=get_settings()
    )
    assert stub.calls == 2
    assert obs.raw_fallback is False
    assert obs.keep is True
    assert "resampled" in obs.verdict
    assert obs.candidates[0]["content"] == "Pin all dependencies."


@pytest.mark.asyncio
async def test_double_spiral_still_raws(db, monkeypatch):
    stub = SpiralAlways()

    async def fake_resolve():
        return stub

    monkeypatch.setattr(observer, "resolve_provider", fake_resolve)
    emb = Embedder(Settings())
    obs = await observer.observe(
        db=db, embedder=emb, turn=_turn(), settings=get_settings()
    )
    assert stub.calls == 2  # one retry, not a loop
    assert obs.raw_fallback is True
    assert "finish=length" in obs.verdict, obs.verdict


class ClerkStub:
    """Answers keep=false instantly; call count proves the gate passed."""

    name = "stub"

    def __init__(self) -> None:
        self.calls = 0

    async def healthy(self) -> bool:
        return True

    async def complete(self, messages, *, max_tokens=1024, json_object=False,
                       reasoning_effort=None):
        self.calls += 1
        assert reasoning_effort == "minimal", \
            "clerk tasks must not pay thinker budgets"
        return Completion(
            text='{"keep": false, "salience": 0.1, "candidates": []}',
            model="stub",
        )

    async def close(self) -> None:
        pass


def _kill_provider(monkeypatch):
    monkeypatch.setenv("TOTTIE_PROVIDER", "meta")
    monkeypatch.setenv("META_BASE_URL", "http://127.0.0.1:9")  # dead port
    get_settings.cache_clear()
    from app.providers import resolve as resolve_mod

    resolve_mod._cache.clear()


@pytest.mark.asyncio
async def test_familiar_repeat_skips_without_llm(db, monkeypatch):
    """A repeated turn never reaches the model — dead provider still gets a
    verdict — and the known row gets rehearsed (access bump)."""
    from tests.test_recall import seed

    emb = Embedder(Settings())
    ids = await seed(db, emb, "fam", [
        {"name": "todo",
         "content": "BusinessManager todo.txt is currently empty.",
         "tags": ["todos"]},
    ])
    _kill_provider(monkeypatch)
    turn = WorkerTurn(
        text="BusinessManager todo.txt is currently empty.",
        session_id="fam", turn=1, owner="fam",
        trust="user_direct", origin=None, client_event_id="e2",
    )
    obs = await observer.observe(
        db=db, embedder=emb, turn=turn, settings=get_settings()
    )
    assert obs.keep is False
    assert obs.provider == "none"
    assert "familiar" in obs.verdict and "already known" in obs.verdict
    row = await db.fetchrow(
        "SELECT access_count FROM memories WHERE id = %s::uuid",
        (ids["todo"],),
    )
    assert row["access_count"] == 1


@pytest.mark.asyncio
async def test_topical_novelty_passes_gate(db, monkeypatch):
    """Dogfood turn 10: topical but store-novel must reach the model. The
    scripted clerk records the call; the old centroid gate dropped this."""
    from tests.test_recall import seed

    emb = Embedder(Settings())
    await seed(db, emb, "fam2", [
        {"name": "a", "content": "NTbill backend is Fastify plus Postgres.",
         "tags": ["ntbill"]},
        {"name": "b", "content": "NTbill is an invoicing app.",
         "tags": ["ntbill", "invoicing"]},
        {"name": "c", "content": "BusinessManager todo list is empty.",
         "tags": ["todos"]},
    ])
    stub = ClerkStub()

    async def fake_resolve():
        return stub

    monkeypatch.setattr(observer, "resolve_provider", fake_resolve)
    turn = WorkerTurn(
        text="NTbill gaps before real customers: email delivery off, "
        "no Paddle account so checkout 503s, auth tokens in AsyncStorage "
        "not keychain, public portal tokens not revocable.",
        session_id="fam2", turn=3, owner="fam2",
        trust="user_direct", origin=None, client_event_id="e1",
    )
    obs = await observer.observe(
        db=db, embedder=emb, turn=turn, settings=get_settings()
    )
    assert stub.calls == 1, "topical-novel turn never reached the model"
    assert obs.verdict.startswith("model keep=false"), obs.verdict


@pytest.mark.asyncio
async def test_repeat_revives_ranked_out(db, monkeypatch):
    """Re-mentioning a ranked-out memory revives it: the real revival path,
    not the probe nobody calls."""
    from tests.test_recall import seed

    emb = Embedder(Settings())
    ids = await seed(db, emb, "fam3", [
        {"name": "todo",
         "content": "BusinessManager todo.txt is currently empty.",
         "tags": ["todos"]},
    ])
    await db.execute(
        "UPDATE memories SET ranked_out = true WHERE id = %s::uuid",
        (ids["todo"],),
    )
    _kill_provider(monkeypatch)
    turn = WorkerTurn(
        text="BusinessManager todo.txt is currently empty.",
        session_id="fam3", turn=1, owner="fam3",
        trust="user_direct", origin=None, client_event_id="e2",
    )
    obs = await observer.observe(
        db=db, embedder=emb, turn=turn, settings=get_settings()
    )
    assert obs.keep is False and "revived" in obs.verdict, obs.verdict
    row = await db.fetchrow(
        "SELECT ranked_out FROM memories WHERE id = %s::uuid",
        (ids["todo"],),
    )
    assert row["ranked_out"] is False

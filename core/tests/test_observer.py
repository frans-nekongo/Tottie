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

    async def complete(self, messages, *, max_tokens=1024, json_object=False):
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
    async def complete(self, messages, *, max_tokens=1024, json_object=False):
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

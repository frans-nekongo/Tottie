"""Provider switch: explicit modes are type-pure, auto prefers live meta,
typos fail loud. One live Meta smoke call; local skips honestly when down."""
import pytest

from app.providers.base import ProviderError
from app.providers.local import LocalProvider
from app.providers.meta import MetaProvider
from app.providers.resolve import resolve_provider


@pytest.mark.asyncio
async def test_explicit_modes_need_no_health(monkeypatch):
    monkeypatch.setenv("TOTTIE_PROVIDER", "meta")
    p = await resolve_provider()
    assert p.name == "meta"
    await p.close()
    monkeypatch.setenv("TOTTIE_PROVIDER", "local")
    p = await resolve_provider()
    assert p.name == "local"
    await p.close()


@pytest.mark.asyncio
async def test_invalid_mode_fails_loud(monkeypatch):
    monkeypatch.setenv("TOTTIE_PROVIDER", "bogus")
    with pytest.raises(ProviderError):
        await resolve_provider()


@pytest.mark.asyncio
async def test_auto_prefers_live_meta(monkeypatch):
    monkeypatch.setenv("TOTTIE_PROVIDER", "auto")
    p = await resolve_provider()
    assert p.name == "meta"  # key is live; local may or may not exist
    await p.close()


@pytest.mark.asyncio
async def test_meta_live_complete(monkeypatch):
    from app.config import Settings

    creds = Settings()  # same source the app uses: env > Tottie/.env
    key, base, model = creds.meta_api_key, creds.meta_base_url, creds.meta_model
    if not key:
        pytest.skip("no META_API_KEY in env or .env")
    p = MetaProvider(base, key, model)
    try:
        assert await p.healthy()
        # 512 floor: the reasoning model burns ~150 tokens before emitting
        # even one word; 64 ends finish=length with empty content (verified).
        r = await p.complete(
            [{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=512,
        )
        assert "OK" in r.text
    finally:
        await p.close()


@pytest.mark.asyncio
async def test_local_skips_when_down():
    import os

    p = LocalProvider(
        os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:11434"),
        os.environ.get("LOCAL_LLM_MODEL", "nkngo-qwen-coder-3b"),
    )
    try:
        if not await p.healthy():
            pytest.skip("ollama down — local is the fallback, honest skip")
        r = await p.complete(
            [{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=64,
        )
        assert "OK" in r.text
    finally:
        await p.close()


def test_query_prefix_is_bge_only():
    """MiniLM A/B: bare 5/6 top-1 vs prefixed 4/6, cosines down everywhere,
    German HIT -> miss. The BGE instruction is BGE's, nobody else's."""
    from app.embeddings import QUERY_PREFIX, query_prefix_for

    assert query_prefix_for("BAAI/bge-small-en-v1.5") == QUERY_PREFIX
    assert query_prefix_for("BAAI/bge-m3") == QUERY_PREFIX
    assert query_prefix_for(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2") == ""


def test_clip_budget_fits_smallest_window():
    """512 chars ~= 128 tokens: honest truncation flag for every model,
    including MiniLM's 128-token window."""
    from app.embeddings import CHAR_BUDGET, Embedder

    assert CHAR_BUDGET == 512
    text, cut = Embedder._clip("x" * 600)
    assert cut is True and len(text) == 512
    text, cut = Embedder._clip("short")
    assert (text, cut) == ("short", False)

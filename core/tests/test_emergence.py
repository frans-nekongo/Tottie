"""Emergent categories: reuse, mint, merge. The tag AND kind spaces
self-organize; nothing is enumerated by hand (regression-guarded).
Deterministic except the one live reuse run."""
import pytest

from app.agents import observer
from app.agents.consolidate import merge_kinds, merge_tags
from app.config import Settings
from app.embeddings import Embedder
from tests.test_recall import seed as _seed

from tests.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


@pytest.mark.asyncio
async def test_vocabulary_orders_by_frequency(db, emb):
    ow = "emv"
    await _seed(db, emb, ow, [
        {"name": "a", "content": "Cheese is dairy.", "tags": ["food"]},
        {"name": "b", "content": "Milk is dairy.", "tags": ["food"]},
        {"name": "c", "content": "Deploy on Friday.", "tags": ["deploy"]},
        {"name": "d", "content": "A stray preference.",
         "tags": ["preference"]},
    ])
    vocab = await observer.tag_vocabulary(db, ow)
    assert vocab[0] == "food", vocab  # most used first
    assert "deploy" in vocab
    assert "preference" not in vocab, "kind-words are not categories"
    assert await observer.tag_vocabulary(db, ow, limit=1) == ["food"]


def test_prompt_has_no_fixed_list():
    assert "money, routine" not in observer.SYSTEM
    assert "food, health, work" not in observer.SYSTEM
    assert "mint" in observer.SYSTEM and "reuse" in observer.SYSTEM.lower()
    assert "identity|convention|decision" not in observer.SYSTEM
    assert "closed claim type" not in observer.SYSTEM
    assert "assimilation" in observer.SYSTEM
    assert "accommodation" in observer.SYSTEM
    assert "2-4" not in observer.SYSTEM


@pytest.mark.asyncio
async def test_kind_vocabulary_orders_by_frequency(db, emb):
    ow = "emkv"
    await _seed(db, emb, ow, [
        {"name": "a", "content": "Cheese is dairy.", "kind": "preference"},
        {"name": "b", "content": "Milk is dairy.", "kind": "preference"},
        {"name": "c", "content": "Deploy on Friday.", "kind": "ritual"},
    ])
    vocab = await observer.kind_vocabulary(db, ow)
    assert vocab[0] == "preference", vocab
    assert "ritual" in vocab  # minted words join the space


@pytest.mark.asyncio
async def test_kind_merge_folds_near_dupes(db, emb):
    ow = "emkm"
    await _seed(db, emb, ow, [
        {"name": "a", "content": "Ate rice for lunch.", "kind": "habit"},
        {"name": "b", "content": "Ate rice for lunch today.", "kind": "habit"},
        {"name": "c", "content": "Ate rice for lunch again.",
         "kind": "habits"},
    ])
    out = await merge_kinds(db, ow)
    assert out["merged"] == 1, out
    assert out["pairs"][0]["keep"] == "habit", out
    left = await db.fetch(
        "SELECT DISTINCT kind FROM memories WHERE owner = %s", (ow,))
    assert {r["kind"] for r in left} == {"habit"}, left


@pytest.mark.asyncio
async def test_kind_merge_keeps_distant_apart(db, emb):
    ow = "emkd"
    await _seed(db, emb, ow, [
        {"name": "a", "content": "Ate rice for lunch.", "kind": "habit"},
        {"name": "b", "content": "Deployed the payments service.",
         "kind": "ritual"},
    ])
    out = await merge_kinds(db, ow)
    assert out["merged"] == 0, out


@pytest.mark.asyncio
async def test_merge_folds_near_dupes(db, emb):
    ow = "emm"
    await _seed(db, emb, ow, [
        {"name": "a", "content": "Ate rice for lunch.",
         "tags": ["food"]},
        {"name": "b", "content": "Ate rice for lunch today.",
         "tags": ["food"]},
        {"name": "c", "content": "Ate rice for lunch again.",
         "tags": ["foods"]},
    ])
    out = await merge_tags(db, ow)
    assert out["merged"] == 1, out
    assert out["pairs"][0]["keep"] == "food", out
    left = await db.fetch(
        "SELECT DISTINCT unnest(tags) AS t FROM memories WHERE owner = %s",
        (ow,),
    )
    assert {r["t"] for r in left} == {"food"}, left


@pytest.mark.asyncio
async def test_merge_keeps_distant_apart(db, emb):
    ow = "emk"
    await _seed(db, emb, ow, [
        {"name": "a", "content": "Ate rice for lunch.",
         "tags": ["food"]},
        {"name": "b", "content": "Deployed the payments service.",
         "tags": ["deploy"]},
    ])
    out = await merge_tags(db, ow)
    assert out["merged"] == 0, out


@pytest.mark.asyncio
async def test_live_reuse_mints_nothing_new(client, db):
    """Fresh owner: first write mints, second write reuses the first's tags.

    Sequential on purpose: reuse reads committed vocabulary, and the two
    workers curate concurrently. Concurrent mints that diverge are folded by
    Sleep merge (tested deterministically above), and same-session pairs are
    always temporally chained regardless."""
    import asyncio
    import uuid

    ow = f"eml_{uuid.uuid4().hex[:8]}"

    async def _write(text, turn):
        r = await client.post("/write", json={
            "text": text, "session_id": ow, "turn": turn, "owner": ow,
            "source": {"trust": "user_direct"},
        }, headers=AUTH)
        assert r.status_code == 202
        for _ in range(90):
            n = await db.fetchval(
                "SELECT count(*) FROM memory_events WHERE session_id = %s "
                "AND cue IS NULL",
                (ow,),
            )
            if n and n > turn:
                return
            await asyncio.sleep(2)
        raise AssertionError(f"turn {turn} never curated")

    await _write("I hate cheese.", 0)
    await _write("I am vegetarian.", 1)
    verdicts = await db.fetch(
        "SELECT observer_verdict FROM memory_events WHERE session_id = %s "
        "AND cue IS NULL",
        (ow,),
    )
    if any("RAW" in (v["observer_verdict"] or {}).get("reason", "")
           for v in verdicts):
        pytest.skip("provider degraded to RAW fallback; reuse untestable")
    rows = await db.fetch(
        "SELECT content, tags FROM memories WHERE owner = %s "
        "AND valid_to IS NULL",
        (ow,),
    )
    assert len(rows) >= 2
    tags = [set(r["tags"] or []) for r in rows]
    shared = set.intersection(*tags)
    assert shared, f"second write reused nothing: {tags}"

"""Taxonomist: discovered topic/area tags. Real DB + real embeds, pure
cosine + union-find: deterministic, no LLM, no NLI.
"""
import math
import uuid

import pytest
from psycopg.types.json import Json

from app.agents import taxonomist
from app.config import Settings, get_settings
from app.db import pgvector_literal
from app.embeddings import Embedder

HABITS = ["Habit tracker logs daily meditation.",
          "Habit tracker logs daily reading."]
SPLIT = ["Splitter divides groceries Anna double.",
         "Splitter settles taxi fare."]
SOLO = "Quantum entanglement enables teleportation."


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (
        math.sqrt(sum(x * x for x in a))
        * math.sqrt(sum(y * y for y in b)))


async def _seed(db, emb, owner, content):
    vec, _ = await emb.embed(content)
    row = await db.execute_returning(
        "INSERT INTO memories (owner, tier, kind, content, trust, source, "
        "embedding, embedding_model, hash) VALUES "
        "(%s,'knowledge','fact',%s,'user_direct',%s,%s::vector,%s,%s) "
        "RETURNING id",
        (owner, content, Json({"session": "seed", "turn": 0}),
         pgvector_literal(vec), emb.model_name, uuid.uuid4().hex),
    )
    return str(row["id"])


@pytest.mark.asyncio
async def test_discovered_topics(db, emb):
    # Pin the geometry the test relies on: habits = tight topic,
    # split pair below the topic cut, solo shares nothing.
    vecs = [(await emb.embed(c))[0] for c in HABITS + SPLIT + [SOLO]]
    assert _cos(vecs[0], vecs[1]) >= taxonomist.TOPIC_COSINE
    assert "splitter" in SPLIT[0].lower() and "splitter" in SPLIT[1].lower()
    solo_terms = set(HABITS[0].split()) | set(SPLIT[0].split())
    assert not (set(SOLO.lower().split()) & {w.lower() for w in solo_terms}
                - {"the", "a", "is", "in", "of"}), SOLO
    ids = {}
    for i, c in enumerate(HABITS + SPLIT + [SOLO]):
        ids[c] = await _seed(db, emb, "tx1", c)
    out = await taxonomist.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="tx1")
    assert out["topics"] == 4, out
    rows = await db.fetch(
        "SELECT content, tags FROM memories WHERE owner = 'tx1' "
        "AND valid_to IS NULL")
    tags = {r["content"]: r["tags"] for r in rows}

    def topic(c):
        return next(t for t in tags[c] if t.startswith("topic:"))

    assert topic(HABITS[0]) == topic(HABITS[1])  # one topic
    assert topic(SPLIT[0]) != topic(SPLIT[1])  # loose pair stays split
    assert topic(SOLO) not in (topic(HABITS[0]), topic(SPLIT[0]))
    # Idempotent retag: second sweep rewrites, never duplicates tags;
    # stale area: tags from earlier sweeps are scrubbed.
    await db.execute(
        "UPDATE memories SET tags = tags || '{area:stale}' "
        "WHERE owner = 'tx1'")
    await taxonomist.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="tx1")
    rows = await db.fetch(
        "SELECT tags FROM memories WHERE owner = 'tx1' AND valid_to IS NULL")
    for r in rows:
        assert len([t for t in r["tags"] if t.startswith("topic:")]) == 1
        assert not [t for t in r["tags"] if t.startswith("area:")]

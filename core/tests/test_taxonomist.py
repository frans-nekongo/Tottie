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


async def _seed(db, emb, owner, content, session="seed", turn=0):
    vec, _ = await emb.embed(content)
    row = await db.execute_returning(
        "INSERT INTO memories (owner, tier, kind, content, trust, source, "
        "embedding, embedding_model, hash) VALUES "
        "(%s,'knowledge','fact',%s,'user_direct',%s,%s::vector,%s,%s) "
        "RETURNING id",
        (owner, content, Json({"session": session, "turn": turn}),
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
    # Provenance: habits read from school docs, splitter from company
    # docs (no .git up-tree: area = parent dir name), solo from chat.
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance) "
        "VALUES ('tx1','txs',0,'[file read: /tmp/seed-school/a.txt — part "
        "1/1] habits'), ('tx1','txs',1,'[file read: "
        "/tmp/seed-corp/b.md — part 1/1] splitter'), "
        "('tx1','txs',2,'just chatting about teleportation')")
    for c in HABITS:
        await _seed(db, emb, "tx1", c, session="txs", turn=0)
    for c in SPLIT:
        await _seed(db, emb, "tx1", c, session="txs", turn=1)
    await _seed(db, emb, "tx1", SOLO, session="txs", turn=2)
    out = await taxonomist.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="tx1")
    assert out["topics"] == 4, out
    assert sorted(out["areas"]) == ["seed-corp", "seed-school",
                                    "session"], out
    rows = await db.fetch(
        "SELECT content, tags FROM memories WHERE owner = 'tx1' "
        "AND valid_to IS NULL")
    tags = {r["content"]: r["tags"] for r in rows}

    def topic(c):
        return next(t for t in tags[c] if t.startswith("topic:"))

    def area(c):
        return next(t for t in tags[c] if t.startswith("area:"))

    assert topic(HABITS[0]) == topic(HABITS[1])  # one topic
    assert topic(SPLIT[0]) != topic(SPLIT[1])  # loose pair stays split
    assert topic(SOLO) not in (topic(HABITS[0]), topic(SPLIT[0]))
    assert area(HABITS[0]) == area(HABITS[1]) == "area:seed-school"
    assert area(SPLIT[0]) == area(SPLIT[1]) == "area:seed-corp"
    assert area(SOLO) == "area:session"


@pytest.mark.asyncio
async def test_pairs_outside_row_window_do_not_crash(db, emb, monkeypatch):
    # Live case: owner passed ROW_CAP (500) rows; pairs span ALL valid
    # rows but ids is the latest-ROW_CAP window, so an edge touching an
    # old row KeyErrored union-find. Shrink the window instead of
    # seeding 500 rows: 3 tight rows, window of 2, oldest outside.
    rows = ["Window cache uses redis store.",
            "Window cache uses redis store daily.",
            "Window cache uses redis store nightly."]
    vecs = [(await emb.embed(c))[0] for c in rows]
    assert _cos(vecs[0], vecs[1]) >= taxonomist.TOPIC_COSINE
    assert _cos(vecs[0], vecs[2]) >= taxonomist.TOPIC_COSINE
    for i, c in enumerate(rows):
        await _seed(db, emb, "tx3", c, session="txs3", turn=i)
    monkeypatch.setattr(taxonomist, "ROW_CAP", 2)
    out = await taxonomist.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="tx3")
    assert out["rows"] == 2, out
    assert out["topics"] == 1, out


@pytest.mark.asyncio
async def test_own_provenance_beats_topic_vote(db, emb):
    # Live case: 2 company RAG rows landed in school-majority topic
    # qwen (streaming/latency talk). Own file wins over the vote.
    corp = ["Server cache uses redis store.",
            "Server cache uses redis store always."]
    school = "Server cache uses redis store today."
    vecs = [(await emb.embed(c))[0] for c in corp + [school]]
    assert _cos(vecs[0], vecs[1]) >= taxonomist.TOPIC_COSINE
    assert _cos(vecs[0], vecs[2]) >= taxonomist.TOPIC_COSINE
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance) "
        "VALUES ('tx2','txs2',0,'[file read: /tmp/seed-corp/c.md — part "
        "1/1] cache'), ('tx2','txs2',1,'[file read: "
        "/tmp/seed-school/s.txt — part 1/1] cache')")
    for c in corp:
        await _seed(db, emb, "tx2", c, session="txs2", turn=0)
    await _seed(db, emb, "tx2", school, session="txs2", turn=1)
    out = await taxonomist.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="tx2")
    assert out["topics"] == 1, out
    rows = await db.fetch(
        "SELECT content, tags FROM memories WHERE owner = 'tx2' "
        "AND valid_to IS NULL")
    tags = {r["content"]: r["tags"] for r in rows}

    def area(c):
        return next(t for t in tags[c] if t.startswith("area:"))

    assert area(corp[0]) == area(corp[1]) == "area:seed-corp"
    assert area(school) == "area:seed-school"
    # Idempotent retag: second sweep rewrites, never duplicates tags.
    await taxonomist.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="tx1")
    rows = await db.fetch(
        "SELECT tags FROM memories WHERE owner = 'tx1' AND valid_to IS NULL")
    for r in rows:
        assert len([t for t in r["tags"] if t.startswith("topic:")]) == 1
        assert len([t for t in r["tags"] if t.startswith("area:")]) == 1

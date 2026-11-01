"""Curator: junk classification + sweep retirement. classify() is pure
unit territory; the sweep is real DB + real local NLI, no LLM.
"""
import uuid

import pytest
from psycopg.types.json import Json

from app.agents import curator
from app.config import Settings, get_settings
from app.db import pgvector_literal
from app.embeddings import Embedder


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


def test_classify_transient():
    assert curator.classify("Owner is editing scribe now.") == "transient"
    assert curator.classify("Worker is committing step 7.") == "transient"
    assert curator.classify("The observer is intercepting T1 turns.") == \
        "transient"
    # Durable project state is not transient (no micro-verb, no now).
    assert curator.classify(
        "Owner is building a CLI expense splitter.") is None


def test_classify_husk():
    assert curator.classify("Reversal was verified.") == "husk"
    assert curator.classify("The artifact was verified.") == "husk"
    assert curator.classify("Updater is green.") == "husk"
    # Short active sentences carry events: spared.
    assert curator.classify("Ben now drinks.") is None
    assert curator.classify("Anna paid for the taxi home.") is None
    assert curator.classify("Owner plans to add the test.") is None
    # Digits and quotes save short states.
    assert curator.classify("Total pages: 740.") is None
    assert curator.classify('Done: "Dune" marked read.') is None


async def _seed(db, emb, owner, content, session="cs", turn=0):
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
async def test_sweep_retires_transient_and_husk(db, emb):
    await _seed(db, emb, "cu1", "Owner is editing scribe now.")
    await _seed(db, emb, "cu1", "Reversal was verified.", turn=1)
    keep = await _seed(db, emb, "cu1",
                       "Owner is building a CLI expense splitter.", turn=2)
    out = await curator.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="cu1")
    assert out["retired"] == 2, out
    live = await db.fetch(
        "SELECT id FROM memories WHERE owner = 'cu1' AND valid_to IS NULL")
    assert [str(r["id"]) for r in live] == [keep]


@pytest.mark.asyncio
async def test_sweep_retires_nli_drift(db, emb):
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance) "
        "VALUES ('cu2','cs2',0,'The server is up and healthy.')")
    await _seed(db, emb, "cu2", "The production server is completely down.",
                session="cs2")
    await _seed(db, emb, "cu2",
                "Server health is good and steady today overall.",
                session="cs2")
    out = await curator.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="cu2")
    assert out["retired"] == 1, out
    live = await db.fetch(
        "SELECT content FROM memories WHERE owner = 'cu2' "
        "AND valid_to IS NULL")
    assert [r["content"] for r in live] == [
        "Server health is good and steady today overall."]

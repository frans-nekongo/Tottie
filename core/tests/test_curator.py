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


@pytest.mark.asyncio
async def test_drift_keeps_merged_row_from_long_turn(db, emb):
    # Regression: whole-turn NLI inverted on 2k-char premises (entailed
    # rows read contradiction 0.95+) and the curator massacred 15
    # innocent doc rows. Merged-but-supported rows must survive.
    filler = ("The quarterly review covered budgets, hiring plans, office "
              "snacks, travel policy, and the new parking rules. ")
    turn = (filler * 30
            + "NKNGO standardizes base images on node:20-alpine for web "
            "and python:3.12-slim for backends. "
            + filler * 30)
    assert len(turn) > 2000
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance) "
        "VALUES ('cu3','cs3',0,%s)", (turn,))
    await _seed(db, emb, "cu3",
                "NKNGO standardizes base images on node:20-alpine for web "
                "and python:3.12-slim for backends.",
                session="cs3")
    await _seed(db, emb, "cu3",
                "The office voted to keep the office parrot permanently.",
                session="cs3", turn=0)
    out = await curator.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="cu3")
    live = await db.fetch(
        "SELECT content FROM memories WHERE owner = 'cu3' "
        "AND valid_to IS NULL")
    contents = [r["content"] for r in live]
    assert any("node:20-alpine" in c for c in contents), (out, contents)
    assert not any("parrot" in c for c in contents), (out, contents)


@pytest.mark.asyncio
async def test_drift_checks_all_merge_turns(db, emb):
    # Reconcile UPDATE appends content from a later turn; the drift
    # check must verify each clause against the pooled turns, or true
    # merged rows retire (live case: standalone row fused turn 143 +
    # turn 145, convicted twice on turn 143 alone).
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance) "
        "VALUES ('cu4','cs4',0,'Docker builds use multi-stage caching.')")
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance) "
        "VALUES ('cu4','cs4',1,'Standalone mode shrank the app image.')")
    vec, _ = await emb.embed("Docker builds use multi-stage caching.\n"
                             "Standalone mode shrank the app image.")
    await db.execute(
        "INSERT INTO memories (owner, tier, kind, content, trust, source, "
        "embedding, embedding_model, hash) VALUES "
        "('cu4','knowledge','fact',%s,'user_direct',%s,%s::vector,%s,%s)",
        ("Docker builds use multi-stage caching.\n"
         "Standalone mode shrank the app image.",
         Json({"session": "cs4", "turn": 0, "turns": [0, 1]}),
         pgvector_literal(vec), emb.model_name, uuid.uuid4().hex),
    )
    out = await curator.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="cu4")
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = 'cu4' "
        "AND valid_to IS NULL")
    assert n == 1, out

"""Ranker: retrievability curve math + sweep directions. Pure SQL and
math: deterministic, no NLI, no LLM.
"""
import uuid

import pytest
from psycopg.types.json import Json

from app.agents import ranker
from app.config import Settings
from app.db import pgvector_literal
from app.embeddings import Embedder


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


def test_retrievability_curve_shape():
    assert ranker.retrievability(0, 1.0) == 1.0
    assert ranker.retrievability(30, 1.0) < ranker.RANK_FLOOR
    assert ranker.retrievability(30, 365.0) > 0.9
    assert ranker.retrievability(5, 0.0) == 0.0


async def _seed(db, emb, owner, content, days_ago=0, stability=1.0,
                ranked=False):
    vec, _ = await emb.embed(content)
    row = await db.execute_returning(
        "INSERT INTO memories (owner, tier, kind, content, trust, source, "
        "embedding, embedding_model, hash, created_at, stability, "
        "ranked_out) VALUES (%s,'knowledge','fact',%s,'user_direct',%s,"
        "%s::vector,%s,%s,now() - make_interval(days => %s),%s,%s) "
        "RETURNING id",
        (owner, content, Json({"session": "seed", "turn": 0}),
         pgvector_literal(vec), emb.model_name, uuid.uuid4().hex,
         days_ago, stability, ranked),
    )
    return str(row["id"])


@pytest.mark.asyncio
async def test_sweep_ranks_stale_out_and_practiced_back(db, emb):
    stale = await _seed(db, emb, "rk1", "Stale unpracticed fact.", days_ago=30)
    fresh = await _seed(db, emb, "rk1", "Fresh fact from today.")
    practiced = await _seed(db, emb, "rk1", "Old but practiced fact.",
                            days_ago=30, stability=365.0, ranked=True)
    out = await ranker.run_sweep(
        db=db, embedder=emb, settings=None, owner="rk1")
    assert out == {"ranked_out": 1, "ranked_back": 1, "rows": 3}, out
    flags = await db.fetch(
        "SELECT id, ranked_out FROM memories WHERE owner = 'rk1'")
    by_id = {str(r["id"]): r["ranked_out"] for r in flags}
    assert by_id == {stale: True, fresh: False, practiced: False}

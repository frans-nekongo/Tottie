"""Pool, session GUCs, migrations ledger, vector round-trip — all on tottie_test."""
import pytest

from app.db import pgvector_literal


@pytest.mark.asyncio
async def test_pool_and_gucs(db):
    assert await db.fetchval("SELECT 1") == 1
    assert await db.fetchval("SHOW hnsw.iterative_scan") == "strict_order"
    assert await db.fetchval("SHOW hnsw.ef_search") == "100"


@pytest.mark.asyncio
async def test_migrations_ledger_has_baseline(db):
    rows = await db.fetch("SELECT name FROM schema_migrations ORDER BY 1")
    assert rows and rows[0]["name"] == "000_baseline"


@pytest.mark.asyncio
async def test_vector_roundtrip_with_cast(db):
    emb = [0.01] * 384
    await db.execute(
        "INSERT INTO memories (owner, tier, kind, content, embedding)"
        " VALUES ('t', 'episodic', 'event', 'r', %s::vector)",
        (pgvector_literal(emb),),
    )
    row = await db.fetchrow(
        "SELECT content, embedding <=> %s::vector AS d FROM memories WHERE owner = 't'",
        (pgvector_literal(emb),),
    )
    assert row["content"] == "r"
    assert abs(row["d"]) < 1e-6

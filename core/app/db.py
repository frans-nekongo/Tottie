"""Async Postgres pool, migrations ledger, query helpers.

Rules, from the v6 audit:
- Bound parameters only. Vector params need explicit ``::vector`` casts
  (Postgres resolves no implicit text->vector cast for $n).
- Vectors cross the boundary as text literals (``pgvector_literal``), never via
  per-connection type registration — every pooled connection then behaves
  identically with zero setup state.
- Session GUCs (iterative scan, ef_search) ride in the conninfo ``options`` so
  they apply to every connection the pool ever opens, not just the first ones.
"""
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import Settings

APP_DIR = Path(__file__).resolve().parent
SCHEMA_SQL = APP_DIR / "schema.sql"
MIGRATIONS_DIR = APP_DIR.parent / "migrations"
BASELINE = "000_baseline"


def pgvector_literal(vec: list[float]) -> str:
    """Format an embedding for a ``%s::vector`` parameter. Deterministic, no
    adapter state, works on any connection."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


class Database:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        gucs = (
            "-c%20hnsw.iterative_scan%3Dstrict_order"
            f"%20-c%20hnsw.ef_search%3D{settings.hnsw_ef_search}"
        )
        sep = "&" if "?" in settings.db_url else "?"
        conninfo = f"{settings.db_url}{sep}options={gucs}"
        self.pool = AsyncConnectionPool(
            conninfo,
            min_size=2,
            max_size=10,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    async def open(self) -> None:
        await self.pool.open()
        await self.migrate()

    async def close(self) -> None:
        await self.pool.close()

    async def migrate(self) -> list[str]:
        """Baseline schema.sql once, then apply pending migrations/*.sql in order."""
        applied: list[str] = []
        async with self.pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            cur = await conn.execute("SELECT to_regclass('public.memories') AS t")
            row = await cur.fetchone()
            if not row["t"]:
                await self._run_script(conn, SCHEMA_SQL)
            cur = await conn.execute(
                "SELECT 1 FROM schema_migrations WHERE name = %s", (BASELINE,)
            )
            if not await cur.fetchone():
                # Tables pre-exist (e.g. init_db.sh ran first): adopt, don't rebuild.
                await conn.execute(
                    "INSERT INTO schema_migrations (name) VALUES (%s)", (BASELINE,)
                )
                await conn.commit()
                applied.append(BASELINE)
            cur = await conn.execute("SELECT name FROM schema_migrations")
            done = {r["name"] for r in await cur.fetchall()}
            if MIGRATIONS_DIR.is_dir():
                for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                    if path.stem in done:
                        continue
                    await self._run_script(conn, path)
                    await conn.execute(
                        "INSERT INTO schema_migrations (name) VALUES (%s)",
                        (path.stem,),
                    )
                    await conn.commit()
                    applied.append(path.stem)
        return applied

    @staticmethod
    async def _run_script(conn, path: Path) -> None:
        # Naive split is safe ONLY because our SQL keeps to plain DDL/DML.
        # Dollar-quoted bodies would break it, so they are refused loudly.
        text = path.read_text()
        if "$$" in text:
            raise ValueError(f"{path.name}: dollar-quoting unsupported in migrations")
        for chunk in text.split(";"):
            if chunk.strip():
                await conn.execute(chunk)

    async def fetch(self, query: str, params: tuple = ()) -> list[dict]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(query, params)
            return await cur.fetchall()

    async def fetchrow(self, query: str, params: tuple = ()) -> dict | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(query, params)
            return await cur.fetchone()

    async def fetchval(self, query: str, params: tuple = ()):
        row = await self.fetchrow(query, params)
        return next(iter(row.values())) if row else None

    async def execute(self, query: str, params: tuple = ()) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(query, params)
            await conn.commit()

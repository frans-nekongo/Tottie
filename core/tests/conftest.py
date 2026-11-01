"""Real-DB fixtures. No mocks on the storage path.

Transport note: tests talk to Postgres over the unix socket (host=/tmp), not
TCP — same server, same SQL, sandbox-safe. Production uses TCP; the queries
under test are identical.
"""
import os
import subprocess
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.config import get_settings

CORE_DIR = Path(__file__).resolve().parent.parent
PGUSER = os.environ.get("PGUSER", "fransnekongo")
PGHOST = os.environ.get("PGHOST", "/tmp")
TEST_DB = os.environ.get("TOTTIE_TEST_DB", "tottie_test")
TEST_DB_URL = f"postgresql://{PGUSER}/{TEST_DB}?host={PGHOST}"
TEST_TOKEN = "test-token"
TEST_CACHE_DIR = str(CORE_DIR.parent.parent / "local LLMS")


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def _test_db():
    """Create tottie_test (if missing) and apply schema via the real script."""
    env = {
        **os.environ,
        "PGHOST": PGHOST,
        "PGUSER": PGUSER,
        "TOTTIE_DB_NAME": TEST_DB,
        "PATH": f"/opt/homebrew/opt/postgresql@18/bin:{os.environ.get('PATH', '')}",
    }
    proc = subprocess.run(
        [str(CORE_DIR / "scripts" / "init_db.sh")],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return TEST_DB_URL


@pytest.fixture()
def _clean_tables(_test_db):
    conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    conn.execute("TRUNCATE memories, memory_events, memory_links, intentions")
    conn.close()


@pytest_asyncio.fixture
async def db(_test_db, _clean_tables, monkeypatch):
    """Open Database against tottie_test. No embedder — cheap per test."""
    monkeypatch.setenv("TOTTIE_DB_URL", TEST_DB_URL)
    # Concept expansion calls a live LLM: off in tests (deterministic,
    # offline). Prod enables it via .env; one test stubs it directly.
    monkeypatch.setenv("TOTTIE_RECALL_CONCEPTS", "false")
    get_settings.cache_clear()
    from app.db import Database

    d = Database(get_settings())
    await d.open()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def booted_app(_test_db, _clean_tables, monkeypatch):
    """Full app (lifespan: pool + real embedder), yielded raw for direct ASGI."""
    monkeypatch.setenv("TOTTIE_DB_URL", TEST_DB_URL)
    monkeypatch.setenv("TOTTIE_API_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("EMBEDDING_CACHE_DIR", TEST_CACHE_DIR)
    monkeypatch.setenv("TOTTIE_RECALL_CONCEPTS", "false")
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with LifespanManager(app):
        yield app


@pytest_asyncio.fixture
async def client(booted_app):
    """Full app over in-process ASGI (httpx transport: finite responses only)."""
    transport = ASGITransport(app=booted_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

"""W5 eval special checks: surprise-gating, quarantine, consolidation,
revival. Real DB + real embedder; LLM steps run against the configured
provider (skip-with-reason when none is up). The retrieval path is never
mocked."""
import asyncio
import uuid

import pytest
from psycopg.types.json import Json

from app.agents.retrieve import cluster_hits
from app.config import Settings
from app.db import pgvector_literal
from app.embeddings import Embedder
from app.providers.base import NoProviderAvailable
from app.providers.resolve import resolve_provider
from tests.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


async def _seed_episode(db, emb, owner, content, tags, salience=0.8,
                        with_vector=True):
    vec = None
    if with_vector:
        vec, _ = await emb.embed(content)
    row = await db.execute_returning(
        "INSERT INTO memories (owner, tier, kind, content, summary, tags, "
        "salience, trust, source, embedding, embedding_model) "
        "VALUES (%s, 'episodic', 'event', %s, %s, %s, %s, 'user_direct', "
        "%s, %s::vector, %s) RETURNING id",
        (owner, content, content[:120], tags, salience,
         Json({"session": "seed", "turn": 0}),
         pgvector_literal(vec) if vec is not None else None,
         emb.model_name if vec is not None else None),
    )
    return str(row["id"])


async def _wait_event(db, session, timeout=60):
    for _ in range(timeout):
        ev = await db.fetchrow(
            "SELECT scribe_action FROM memory_events WHERE session_id = %s "
            "ORDER BY id DESC LIMIT 1",
            (session,),
        )
        if ev:
            return ev
        await asyncio.sleep(1)
    return None


async def _wait_memories(db, owner, timeout=90):
    for _ in range(timeout):
        n = await db.fetchval(
            "SELECT count(*) FROM memories WHERE owner = %s", (owner,))
        if n:
            return n
        await asyncio.sleep(1)
    return 0


async def _require_provider():
    try:
        p = await resolve_provider()
    except (NoProviderAvailable, ValueError) as e:
        pytest.skip(f"no provider up — honest skip ({e})")
    await p.close()


@pytest.mark.asyncio
async def test_surprise_gating_chitchat_writes_nothing(client, db):
    ow = f"sg_{uuid.uuid4().hex[:8]}"
    r = await client.post("/write", json={
        "text": "thanks!", "session_id": ow, "turn": 0, "owner": ow,
        "source": {"trust": "user_direct"},
    }, headers=AUTH)
    assert r.status_code == 202
    ev = await _wait_event(db, ow)
    assert ev is not None, "worker never curated the chitchat turn"
    assert ev["scribe_action"]["op"] == "SKIP"
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (ow,))
    assert n == 0, "chitchat wrote memories"


@pytest.mark.asyncio
async def test_surprise_gating_first_fact_lands(client, db):
    ow = f"sgf_{uuid.uuid4().hex[:8]}"
    r = await client.post("/write", json={
        "text": "My sailboat is called Mistral.", "session_id": ow,
        "turn": 0, "owner": ow, "source": {"trust": "user_direct"},
    }, headers=AUTH)
    assert r.status_code == 202
    assert await _wait_memories(db, ow) >= 1


@pytest.mark.asyncio
async def test_quarantine_visible_never_injected(client, db):
    ow = f"qz_{uuid.uuid4().hex[:8]}"
    r = await client.post("/write", json={
        "text": "Frans is the chief executive of Globex.", "session_id": ow,
        "turn": 0, "owner": ow, "source": {"trust": "web"},
    }, headers=AUTH)
    assert r.status_code == 202
    assert await _wait_memories(db, ow) >= 1
    row = await db.fetchrow(
        "SELECT id, quarantined FROM memories WHERE owner = %s", (ow,))
    assert row["quarantined"] is True, "web-sourced claim must quarantine"
    mid = str(row["id"])
    rec = await client.post("/recall", json={
        "query": "Who runs Globex?", "session_id": ow, "owner": ow,
    }, headers=AUTH)
    assert rec.status_code == 200
    card = rec.json()["card"] or ""
    assert "Globex" not in card, "quarantined row leaked into the card"
    assert mid not in {h["id"] for h in rec.json()["hits"]}
    c = await client.post(f"/memories/{mid}/confirm",
                          json={"owner": ow}, headers=AUTH)
    assert c.status_code == 200
    rec2 = await client.post("/recall", json={
        "query": "Who runs Globex?", "session_id": ow, "owner": ow,
    }, headers=AUTH)
    assert "Globex" in (rec2.json()["card"] or ""), \
        "confirmed row must inject"


@pytest.mark.asyncio
async def test_consolidation_sleep_generalises(client, db, emb):
    await _require_provider()
    ow = f"sl_{uuid.uuid4().hex[:8]}"
    for day in ("Monday", "Tuesday", "Wednesday"):
        await _seed_episode(
            db, emb, ow, f"{day}: morning run around the lake, 5k.",
            ["health", "running"], with_vector=False)
    r = await client.post("/consolidate", json={
        "session_id": ow, "owner": ow,
    }, headers=AUTH)
    assert r.status_code == 200
    out = r.json()
    assert out["episodes_replayed"] == 3
    assert out["semantic_error"] is None, out["semantic_error"]
    assert out["semantic_written"] >= 1
    assert out["ranked_out"] == 0  # fresh + salient: nothing to retire
    live = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s AND tier = 'episodic'"
        " AND valid_to IS NULL",
        (ow,),
    )
    assert live == 3, "sleep must never destroy the raw episodes"
    sem = await db.fetch(
        "SELECT id, kind, trust, quarantined FROM memories "
        "WHERE owner = %s AND tier = 'knowledge'",
        (ow,),
    )
    assert len(sem) >= 1
    assert all(s["quarantined"] is False for s in sem)
    assert all(s["trust"] == "model_inferred" for s in sem)
    links = await db.fetchval(
        "SELECT count(*) FROM memory_links WHERE owner = %s "
        "AND relation = 'cooccur'",
        (ow,),
    )
    assert links >= 2, "semantic rows must link their source episodes"
    ev = await db.fetchrow(
        "SELECT scribe_action FROM memory_events WHERE session_id = %s "
        "AND scribe_action->>'op' = 'CONSOLIDATE'",
        (ow,),
    )
    assert ev is not None, "sleep must leave a ledger event"


@pytest.mark.asyncio
async def test_revival_ranked_out_returns_via_probe(client, db, emb):
    ow = f"rv_{uuid.uuid4().hex[:8]}"
    mid = await _seed_episode(
        db, emb, ow, "Sunset at the lake cabin with old friends.",
        ["lake", "cabin"])
    q = {"query": "What happened at the lake cabin?",
         "session_id": ow, "owner": ow}
    before = await client.post("/recall", json=q, headers=AUTH)
    assert before.status_code == 200
    assert mid in {h["id"] for h in before.json()["hits"]}, \
        "cue must hit before rank-out (else the test proves nothing)"
    await db.execute(
        "UPDATE memories SET ranked_out = true WHERE id = %s::uuid", (mid,))
    after = await client.post("/recall", json=q, headers=AUTH)
    assert mid not in {h["id"] for h in after.json()["hits"]}, \
        "ranked-out row leaked into ambient recall"
    probe = await client.get(
        "/probe", params={"tag": "lake", "owner": ow}, headers=AUTH)
    assert probe.status_code == 200
    assert mid in {m["id"] for m in probe.json()["memories"]}, \
        "deliberate probe must revive the ranked-out row"


@pytest.mark.asyncio
async def test_prospective_write_registers_and_recall_fires(db, emb):
    from app.agents import retrieve, scribe
    from app.agents.observer import Observation
    from app.config import get_settings
    from app.queue import WorkerTurn

    ow = f"pm_{uuid.uuid4().hex[:8]}"
    turn = WorkerTurn(text='Remind me to buy thyme when I say "mealplan".',
                      session_id=ow, turn=0, owner=ow, trust="user_direct",
                      origin=None, client_event_id=uuid.uuid4().hex)
    skip = Observation(keep=False, salience=0.1, surprise=0.0,
                       candidates=[], verdict="skip", provider="stub")
    await scribe.persist(db=db, embedder=emb, turn=turn, obs=skip)
    rows = await db.fetch(
        "SELECT content, event_cue, status FROM intentions WHERE owner = %s",
        (ow,),
    )
    assert len(rows) == 1, "write path must register the reminder"
    assert rows[0]["content"] == "buy thyme"
    assert "mealplan" in rows[0]["event_cue"]
    # double registration (write + recall paths) stays one row
    await retrieve.register_reminder(
        db, ow, {"content": "buy thyme", "event_cue": 'I say "mealplan"',
                 "days": 0, "hours": 0})
    n = await db.fetchval(
        "SELECT count(*) FROM intentions WHERE owner = %s", (ow,))
    assert n == 1
    out = await retrieve.recall(
        db=db, embedder=emb, owner=ow,
        query='I say "mealplan", anything for me?', session_id=ow,
        k=8, tiers=None, settings=get_settings())
    fired = [f["content"] for f in out["fired_intentions"]]
    assert fired == ["buy thyme"], "quoted cue must fire the intention"


def test_completer_groups_by_shared_tag():
    hits = [
        {"id": "a", "score": 0.9, "tags": ["project/tottie", "x"]},
        {"id": "b", "score": 0.8, "tags": ["project/tottie"]},
        {"id": "c", "score": 0.7, "tags": ["food"]},
        {"id": "d", "score": 0.6, "tags": []},
    ]
    clusters = cluster_hits(hits)
    assert [c["size"] for c in clusters] == [2, 1, 1]
    assert clusters[0]["label"] == "project/tottie"
    assert clusters[0]["ids"] == ["a", "b"]  # score order inside
    assert clusters[2]["label"] == "ungrouped"
    covered = sorted(i for c in clusters for i in c["ids"])
    assert covered == ["a", "b", "c", "d"]  # every hit exactly once
    assert cluster_hits([]) == []


def test_completer_ignores_kind_namespace():
    """Shared 'preference' is namespace overlap, not a topic: no grouping,
    no kind-word labels (same mush doctrine as link formation)."""
    hits = [
        {"id": "a", "score": 0.9, "tags": ["preference", "food"]},
        {"id": "b", "score": 0.8, "tags": ["preference", "deploy"]},
        {"id": "c", "score": 0.7, "tags": ["preference"]},
    ]
    clusters = cluster_hits(hits)
    assert sorted(c["size"] for c in clusters) == [1, 1, 1]
    assert {c["label"] for c in clusters} == {"food", "deploy", "ungrouped"}


def test_completer_ignores_own_kind():
    """A hit's own kind (legacy or freshly minted) never groups it: two
    'habit' rows sharing only their kind tag stay singletons."""
    hits = [
        {"id": "a", "score": 0.9, "kind": "habit",
         "tags": ["habit", "food"]},
        {"id": "b", "score": 0.8, "kind": "habit",
         "tags": ["habit", "deploy"]},
    ]
    clusters = cluster_hits(hits)
    assert sorted(c["size"] for c in clusters) == [1, 1]
    assert {c["label"] for c in clusters} == {"food", "deploy"}

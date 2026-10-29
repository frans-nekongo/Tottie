"""W5 eval special checks: familiarity-gating, quarantine, consolidation,
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
from app.providers.base import Completion, NoProviderAvailable
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


class CurateStub:
    name = "stub"

    async def healthy(self) -> bool:
        return True

    async def complete(self, messages, *, max_tokens=1024, json_object=False,
                       reasoning_effort=None):
        return Completion(
            text='{"keep": true, "salience": 0.7, "candidates": [{'
            '"kind": "preference", "tier": "knowledge", '
            '"subject": "owner", "predicate": "hates", "object": "cheese", '
            '"content": "Owner hates cheese.", '
            '"tags": ["food", "cheese"], "principle": null}]}',
            model="stub",
        )

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_sleep_curates_raw_rows(db, emb, monkeypatch):
    """The revisit pass: a needs_curation row is rewritten in place against
    the live vocabularies, unflagged, and linked by its new tags."""
    from app.agents import consolidate as cons_mod
    from tests.test_recall import seed as _seed

    async def fake_resolve():
        return CurateStub()

    monkeypatch.setattr(cons_mod, "resolve_provider", fake_resolve)
    ow = f"cu_{uuid.uuid4().hex[:8]}"
    ids = await _seed(db, emb, ow, [
        {"name": "raw", "content": "Cheese is disliked here.",
         "kind": "event", "tier": "knowledge", "tags": []},
        {"name": "anchor", "content": "Owner stocks the fridge with food.",
         "kind": "fact", "tier": "knowledge", "tags": ["food"]},
    ])
    await db.execute(
        "UPDATE memories SET needs_curation = true WHERE id = %s::uuid",
        (ids["raw"],),
    )
    out = await cons_mod._curate_raw(db, ow)
    assert out == {"curated": 1, "failed": 0}, out
    row = await db.fetchrow(
        "SELECT kind, tier, subject, predicate, object, content, tags, "
        "needs_curation FROM memories WHERE id = %s::uuid",
        (ids["raw"],),
    )
    assert row["kind"] == "preference" and row["tier"] == "knowledge"
    assert row["subject"] == "owner" and row["predicate"] == "hates"
    assert row["tags"] == ["food", "cheese"], dict(row)
    assert row["needs_curation"] is False
    link = await db.fetchrow(
        "SELECT reason FROM memory_links WHERE owner = %s "
        "AND src = %s::uuid AND dst = %s::uuid AND relation = 'tag'",
        (ow, ids["raw"], ids["anchor"]),
    )
    assert link and "food" in link["reason"], link


@pytest.mark.asyncio
async def test_sleep_curate_failure_stays_flagged(db, emb, monkeypatch):
    """A dead provider fails the pass honestly: the row stays flagged and
    consolidate() reports curate_error instead of raising."""
    from app.agents import consolidate as cons_mod
    from app.config import get_settings
    from app.providers.base import ProviderError

    async def dead_resolve():
        raise ProviderError("curator down")

    monkeypatch.setattr(cons_mod, "resolve_provider", dead_resolve)
    ow = f"cf_{uuid.uuid4().hex[:8]}"
    mid = await _seed_episode(db, emb, ow, "Muddy unclear memory.", [])
    await db.execute(
        "UPDATE memories SET needs_curation = true, tier = 'knowledge' "
        "WHERE id = %s::uuid",
        (mid,),
    )
    out = await cons_mod.consolidate(
        db=db, embedder=emb, owner=ow, session_id=ow,
        settings=get_settings(),
    )
    assert out["curate_error"] == "ProviderError", out
    assert out["raw_curated"] == 0
    flag = await db.fetchval(
        "SELECT needs_curation FROM memories WHERE id = %s::uuid", (mid,))
    assert flag is True


@pytest.mark.asyncio
async def test_sleep_fades_utility_power_law(client, db, emb):
    """Retrieval strength decays by Wickelgren power law (1 + t/30)^-0.5
    (Wixted: power fits human retention better than exponential):
    untouched-for-60-days fades 1.0 -> 3^-0.5 = 0.577. Ancient weak rows
    hit the 0.05 revival floor. One episode replays, so no LLM runs and
    the math is exactly checkable."""
    from app.config import get_settings

    ow = f"eb_{uuid.uuid4().hex[:8]}"
    mid = await _seed_episode(
        db, emb, ow, "Dusty memory from long ago.", ["dust"])
    await db.execute(
        "UPDATE memories SET utility = 1.0, last_access = now() "
        "- make_interval(days => 60) WHERE id = %s::uuid",
        (mid,),
    )
    old = await _seed_episode(
        db, emb, ow, "Faint trace from years ago.", ["faint"])
    await db.execute(
        "UPDATE memories SET tier = 'knowledge', utility = 0.06, "
        "last_access = now() - make_interval(days => 1825) "
        "WHERE id = %s::uuid",
        (old,),
    )
    r = await client.post("/consolidate", json={
        "session_id": ow, "owner": ow,
    }, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["utility_faded"] == 2
    assert get_settings().utility_half_life_days == 30
    u = await db.fetchval(
        "SELECT utility FROM memories WHERE id = %s::uuid", (mid,))
    assert abs(u - 0.5774) < 0.02, u
    uo = await db.fetchval(
        "SELECT utility FROM memories WHERE id = %s::uuid", (old,))
    assert uo == 0.05, uo


@pytest.mark.asyncio
async def test_sleep_decay_spares_structural_edges(client, db, emb):
    """Associative weights (tag/cooccur) decay; temporal/supersedes edges
    are structure and never weaken."""
    from tests.test_recall import seed as _seed

    ow = f"dc_{uuid.uuid4().hex[:8]}"
    ids = await _seed(db, emb, ow, [
        {"name": "a", "content": "First episode.", "tier": "episodic",
         "kind": "event", "tags": ["x"]},
        {"name": "b", "content": "A knowledge fact.", "tier": "knowledge",
         "kind": "fact", "tags": ["y"]},
    ])
    for rel in ("tag", "temporal", "supersedes"):
        await db.execute(
            "INSERT INTO memory_links (owner, src, dst, relation, weight) "
            "VALUES (%s, %s::uuid, %s::uuid, %s, 1.0)",
            (ow, ids["a"], ids["b"], rel),
        )
    r = await client.post("/consolidate", json={
        "session_id": ow, "owner": ow,
    }, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["links_decayed"] == 1
    got = await db.fetch(
        "SELECT relation, weight FROM memory_links WHERE owner = %s",
        (ow,),
    )
    w = {r["relation"]: r["weight"] for r in got}
    assert w["tag"] == pytest.approx(0.9), w
    assert w["temporal"] == 1.0 and w["supersedes"] == 1.0, w


@pytest.mark.asyncio
async def test_replay_orders_by_surprise(db, emb):
    """Sleep replays highest prediction error first: novelty is what
    consolidation is FOR. recency only breaks ties."""
    from app.agents.consolidate import _replay_episodes
    from app.config import get_settings
    from tests.test_recall import seed as _seed

    ow = f"rp_{uuid.uuid4().hex[:8]}"
    ids = await _seed(db, emb, ow, [
        {"name": "low", "content": "Routine morning coffee.",
         "tier": "episodic", "kind": "event"},
        {"name": "high", "content": "Lightning struck the garden shed.",
         "tier": "episodic", "kind": "event"},
        {"name": "mid", "content": "Mail arrived a day early.",
         "tier": "episodic", "kind": "event"},
    ])
    for name, s in (("low", 0.1), ("high", 0.9), ("mid", 0.5)):
        await db.execute(
            "UPDATE memories SET surprise = %s WHERE id = %s::uuid",
            (s, ids[name]),
        )
    got = await _replay_episodes(db, ow, get_settings())
    assert [str(r["id"]) for r in got] == [
        ids["high"], ids["mid"], ids["low"]]


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

"""Recall over seeded rows: real DB, real embedder, no LLM (except the one
live round-trip). Seeds embed their content exactly like the Scribe does."""
import asyncio
import re
import uuid

import pytest
from psycopg.types.json import Json

from app.config import Settings
from app.db import pgvector_literal
from app.embeddings import Embedder
from tests.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
OWNER = "r2"


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


async def seed(db, emb, owner, items):
    """Insert memory rows with real embeddings. Returns {name: id}."""
    ids = {}
    for i, it in enumerate(items):
        vec, _ = await emb.embed(it["content"])
        row = await db.execute_returning(
            "INSERT INTO memories (owner, tier, kind, content, tags, salience, "
            "trust, source, embedding, embedding_model, hash, quarantined, "
            "valid_to, principle) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s,%s,%s,%s) "
            "RETURNING id",
            (
                owner, it.get("tier", "knowledge"), it.get("kind", "fact"),
                it["content"], it.get("tags", []), it.get("salience", 0.7),
                it.get("trust", "user_direct"),
                Json({"session": it.get("session", "seed"), "turn": i}),
                pgvector_literal(vec), emb.model_name, uuid.uuid4().hex,
                it.get("quarantined", False), it.get("valid_to"),
                it.get("principle", ""),
            ),
        )
        ids[it.get("name", f"row{i}")] = str(row["id"])
    return ids


SEEDS = [
    {"name": "name", "tier": "identity", "kind": "identity",
     "content": "The user's name is Recallia.", "tags": ["user"]},
    {"name": "deploy", "kind": "decision",
     "content": "Deploy checklist lives in the runbook under Friday procedures.",
     "tags": ["deploy", "project/A"]},
    {"name": "lake", "tier": "episodic", "kind": "event",
     "content": "Photos from the lake house weekend with old friends.",
     "tags": ["personal"]},
    {"name": "quar", "kind": "decision",
     "content": "Deploy checklist says ship on Fridays without review.",
     "tags": ["deploy"], "trust": "web", "quarantined": True},
    {"name": "old", "kind": "fact",
     "content": "Deploy checklist was kept on a sticky note.",
     "tags": ["deploy"], "valid_to": "2020-01-01"},
]


@pytest.mark.asyncio
async def test_ranked_recall_finds_answer(client, db, emb):
    await seed(db, emb, OWNER, SEEDS)
    r = await client.post("/recall", json={
        "query": "Where is the deploy checklist?", "session_id": "s",
        "owner": OWNER,
    }, headers=AUTH)
    assert r.status_code == 200
    out = r.json()
    assert out["abstain"] is False
    assert out["mode"] == "ranked"
    assert "runbook" in out["hits"][0]["summary"]
    assert out["hits"][0]["why"].startswith("QUESTION -> ")
    assert "Recallia" in out["card"]  # identity header always rides along
    assert out["path"], "story path missing"
    assert out["candidates_matched"] >= 1
    # ledger + rehearsal
    ev = await db.fetchrow(
        "SELECT cue FROM memory_events WHERE utterance LIKE %s",
        ("Where is the deploy%",),
    )
    assert ev["cue"]["type"] == "QUESTION"
    n = await db.fetchval(
        "SELECT access_count FROM memories WHERE content LIKE %s",
        ("%runbook%",),
    )
    assert n >= 1


@pytest.mark.asyncio
async def test_quarantine_superseded_owner_never_leak(client, db, emb):
    other = await seed(db, emb, "intruder", [
        {"name": "x", "content": "Deploy checklist intruder copy.", "tags": ["deploy"]},
    ])
    mine = await seed(db, emb, OWNER, SEEDS)
    r = await client.post("/recall", json={
        "query": "deploy checklist", "session_id": "s", "owner": OWNER, "k": 20,
    }, headers=AUTH)
    got = {h["id"] for h in r.json()["hits"]}
    assert mine["quar"] not in got, "quarantined row injected"
    assert mine["old"] not in got, "superseded row injected"
    assert other["x"] not in got, "cross-owner leak"
    assert mine["deploy"] in got


@pytest.mark.asyncio
async def test_abstain_on_empty_store(client):
    r = await client.post("/recall", json={
        "query": "What is the meaning of life?", "session_id": "s",
        "owner": "nobody",
    }, headers=AUTH)
    out = r.json()
    assert out["abstain"] is True
    assert out["confidence"] == 0.0
    assert out["card"] is None
    assert out["hits"] == []


@pytest.mark.asyncio
async def test_tiers_filter(client, db, emb):
    await seed(db, emb, OWNER, SEEDS)
    r = await client.post("/recall", json={
        "query": "deploy", "session_id": "s", "owner": OWNER, "tiers": ["episodic"],
    }, headers=AUTH)
    assert {h["tier"] for h in r.json()["hits"]} <= {"episodic"}
    r = await client.post("/recall", json={
        "query": "deploy", "session_id": "s", "owner": OWNER, "tiers": ["bogus"],
    }, headers=AUTH)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_command_policy_assembles_kit(client, db, emb):
    await seed(db, emb, OWNER, SEEDS)
    r = await client.post("/recall", json={
        "query": "Show the deploy checklist for #project/A",
        "session_id": "s", "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert out["cue"]["type"] == "COMMAND"
    assert out["cue"]["policy"] == "command"
    assert any(h["kind"] == "decision" for h in out["hits"])


@pytest.mark.asyncio
async def test_lexical_leg_stems_and_strips(client, db, emb):
    """The 'english' config is load-bearing: stemming + stopwords let a
    WH-question hit lexically (proven: 'simple' misses it)."""
    ids = await seed(db, emb, OWNER, [
        {"name": "vault", "content": "The office vault code is 1111.",
         "tags": ["vault"]},
    ])
    r = await client.post("/recall", json={
        "query": "What is the vault code?", "session_id": "s",
        "owner": OWNER,
    }, headers=AUTH)
    hits = {h["id"]: h for h in r.json()["hits"]}
    assert ids["vault"] in hits
    assert "lexical #" in hits[ids["vault"]]["why"], hits[ids["vault"]]


@pytest.mark.asyncio
async def test_non_english_question_recalls(client, db, emb):
    """A German ? question classifies QUESTION and surfaces the German row
    (presence, not rank: bge is English-tuned; MiniLM ranks it top-1)."""
    ids = await seed(db, emb, OWNER, [
        {"name": "de", "content": "Der Tresorcode lautet 2222.",
         "tags": ["tresor"]},
        {"name": "en", "content": "The garden grows tomatoes.",
         "tags": ["garden"]},
    ])
    r = await client.post("/recall", json={
        "query": "Wie lautet der Tresorcode?", "session_id": "s",
        "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert out["cue"]["type"] == "QUESTION"
    assert ids["de"] in {h["id"] for h in out["hits"]}, out["hits"]


@pytest.mark.asyncio
async def test_recall_rehearses_utility(client, db, emb):
    """Serving a hit is retrieval practice (the testing effect): utility
    climbs +0.15 and access is logged."""
    ids = await seed(db, emb, OWNER, [
        {"name": "ramen", "content": "The user adores midnight ramen.",
         "tags": ["food"]},
    ])
    await db.execute(
        "UPDATE memories SET utility = 0.5 WHERE id = %s::uuid",
        (ids["ramen"],),
    )
    r = await client.post("/recall", json={
        "query": "midnight ramen", "session_id": "s", "owner": OWNER,
    }, headers=AUTH)
    assert ids["ramen"] in {h["id"] for h in r.json()["hits"]}
    row = await db.fetchrow(
        "SELECT utility, access_count FROM memories WHERE id = %s::uuid",
        (ids["ramen"],),
    )
    assert row["utility"] == pytest.approx(0.65), dict(row)
    assert row["access_count"] == 1


@pytest.mark.asyncio
async def test_command_policy_boosts_principled_rows(client, db, emb):
    """Actionability emerges from principles, not kind lists: twin rows,
    one carrying a reusable rule — the COMMAND boost ranks it first."""
    ids = await seed(db, emb, OWNER, [
        {"name": "plain", "content": "Deploy checklist lives in the runbook.",
         "kind": "note", "tags": ["deploy"]},
        {"name": "ruled", "content": "Deploy checklist lives in the runbook.",
         "kind": "note", "tags": ["deploy"]},
    ])
    await db.execute(
        "UPDATE memories SET principle = %s WHERE id = %s::uuid",
        ("Always check the list before Friday.", ids["ruled"]),
    )
    r = await client.post("/recall", json={
        "query": "Show the deploy checklist", "session_id": "s",
        "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert out["cue"]["policy"] == "command"
    assert out["hits"][0]["id"] == ids["ruled"], \
        [h["id"] for h in out["hits"]]


@pytest.mark.asyncio
async def test_bfs_surfaces_associated_row(client, db, emb):
    ids = await seed(db, emb, OWNER, SEEDS)
    await db.execute(
        "INSERT INTO memory_links (owner, src, dst, relation, weight) "
        "VALUES (%s, %s::uuid, %s::uuid, 'tag', 1.0)",
        (OWNER, ids["deploy"], ids["lake"]),
    )
    r = await client.post("/recall", json={
        "query": "deploy checklist runbook Friday procedures",
        "session_id": "s", "owner": OWNER, "k": 8,
    }, headers=AUTH)
    lake = [h for h in r.json()["hits"] if h["id"] == ids["lake"]]
    assert lake, "BFS missed the linked row"


@pytest.mark.asyncio
async def test_prospective_fires_and_registers(client, db, emb):
    await seed(db, emb, OWNER, SEEDS)
    await db.execute(
        "INSERT INTO intentions (owner, content, time_cue) "
        "VALUES (%s, 'past due', now() - interval '1 hour')"
        ", (%s, 'future', now() + interval '1 day')",
        (OWNER, OWNER),
    )
    r = await client.post("/recall", json={
        "query": "remind me to water the plants tomorrow",
        "session_id": "s", "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert [f["content"] for f in out["fired_intentions"]] == ["past due"]
    assert out["registered_intention"]["content"] == "water the plants"
    assert out["registered_intention"]["time_cue"] is not None
    n = await db.fetchval(
        "SELECT count(*) FROM intentions WHERE owner = %s AND status = 'pending'",
        (OWNER,),
    )
    assert n == 2  # future + newly registered


@pytest.mark.asyncio
async def test_intentions_fire_exactly_once(client, db, emb):
    """Time and event intentions fire on the matching recall, flip to
    fired, and never fire again; unrelated queries fire nothing new."""
    await seed(db, emb, OWNER, SEEDS)
    await db.execute(
        "INSERT INTO intentions (owner, content, time_cue) "
        "VALUES (%s, 'past due', now() - interval '1 hour')",
        (OWNER,),
    )
    await db.execute(
        "INSERT INTO intentions (owner, content, event_cue) "
        "VALUES (%s, 'stretch', %s)",
        (OWNER, Json(["stand up"])),
    )

    async def _fired(query):
        r = await client.post("/recall", json={
            "query": query, "session_id": "s", "owner": OWNER,
        }, headers=AUTH)
        return sorted(f["content"] for f in r.json()["fired_intentions"])

    # event cues fire on marked spans (quotes/tags = salient cues)
    assert await _fired('I "stand up" now, anything for me?') == [
        "past due", "stretch"]
    assert await _fired('I "stand up" now, anything for me?') == []
    assert await _fired("What is the deploy checklist?") == []
    n = await db.fetchval(
        "SELECT count(*) FROM intentions WHERE owner = %s AND status = 'fired'",
        (OWNER,),
    )
    assert n == 2


@pytest.mark.asyncio
async def test_commanded_principle_outranks_twin(db, emb, monkeypatch):
    """COMMAND policy: among near-identical twins the row carrying a
    reusable principle wins — actionability emerges from the Scribe's
    principle field, never from a kind list."""
    from app.agents import retrieve

    ow = f"rc_{uuid.uuid4().hex[:8]}"
    content = "Deploy procedure ships behind a flag on Fridays."
    ids = await seed(db, emb, ow, [
        {"name": "plain", "kind": "decision", "content": content,
         "tags": ["deploy"]},
        {"name": "ruled", "kind": "decision", "content": content,
         "tags": ["deploy"], "principle": "Always ship behind a flag."},
    ])
    kw = dict(db=db, embedder=emb, owner=ow, session_id="s", k=8,
              tiers=None, settings=Settings())
    boosted = await retrieve.recall(
        query="Show me the deploy procedure", **kw)
    hits = boosted["hits"]
    assert {h["id"] for h in hits} >= set(ids.values())
    assert hits[0]["id"] == ids["ruled"], [h["id"] for h in hits]
    score_b = hits[0]["score"]
    # Ablation: with the boost removed the 1.5x multiplier vanishes
    # exactly — the twin wins by boost, never by leg luck.
    monkeypatch.setattr(retrieve, "COMMAND_BOOST", 1.0)
    unboosted = await retrieve.recall(
        query="Show me the deploy procedure", **kw)
    by_id = {h["id"]: h["score"] for h in unboosted["hits"]}
    assert score_b == pytest.approx(1.5 * by_id[ids["ruled"]], rel=2e-2)


@pytest.mark.asyncio
async def test_recall_pins_identity_slice_unconditionally(db, emb):
    """The human path keeps the pinned identity slice on EVERY recall
    (briefs gate it; recall never does): standing facts about the owner
    survive any query. The YOLO lesson as a test — s23's standing-fact
    promise, fulfilled here instead of the harness."""
    from app.agents import retrieve

    ow = f"rc_{uuid.uuid4().hex[:8]}"
    await seed(db, emb, ow, [
        {"name": "who", "tier": "identity", "kind": "identity",
         "content": "Owner is Amara Quietstorm.", "tags": ["owner"]},
        {"name": "work", "kind": "fact",
         "content": "Streak counts back from today if done.",
         "tags": ["streak"]},
    ])
    out = await retrieve.recall(
        db=db, embedder=emb, owner=ow, session_id="s", k=8,
        tiers=None, settings=Settings(),
        query="how do streaks count")
    assert "Amara Quietstorm" in (out["card"] or "")


def test_retrieval_probability_logistic_mapping():
    """Fix 4: ACT-R P = logistic((A - tau)/s). Pure math, no DB: floor
    maps to exactly 0.5, strong recalls saturate near 1, garbage sinks,
    and the abstain boundary is exactly A < tau (no rounding sliver)."""
    from app.agents.retrieve import retrieval_probability

    assert retrieval_probability(0.35, 0.35) == 0.5
    assert retrieval_probability(0.894, 0.35) == pytest.approx(
        0.9957, rel=1e-3)
    assert retrieval_probability(0.244, 0.35) == pytest.approx(
        0.2573, rel=1e-3)
    assert retrieval_probability(0.0, 0.35) == pytest.approx(
        0.0293, rel=1e-3)
    for a, want in ((0.3499, True), (0.35, False), (0.3501, False)):
        assert (retrieval_probability(a, 0.35) < 0.5) == want


@pytest.mark.asyncio
async def test_assoc_leg_fan_effect_specific_beats_mush(db, emb):
    """ACT-R fan effect (Fix 2): association S - ln(fan). One row sharing
    a rare tag (fan 1, assoc 2.0) outranks nine rows sharing an overloaded
    tag (fan 9, assoc -0.2) in the tag leg — even at much lower salience.
    No LLM: seeded rows, direct recall."""
    from app.agents import retrieve

    ow = f"fan_{uuid.uuid4().hex[:8]}"
    items = [
        {"name": f"d{i}", "kind": "fact",
         "content": f"Deploy pipeline note number {i}.", "tags": ["deploy"],
         "salience": 0.9}
        for i in range(9)
    ] + [{"name": "rare", "kind": "fact",
          "content": "The outage postmortem is scheduled.",
          "tags": ["wednesday-deadline"], "salience": 0.1}]
    ids = await seed(db, emb, ow, items)
    out = await retrieve.recall(
        db=db, embedder=emb, owner=ow, session_id="s", k=20,
        tiers=None, settings=Settings(),
        query="status of #deploy #wednesday-deadline")
    ranks = {}
    for h in out["hits"]:
        m = re.search(r"tag #(\d+)", h.get("why") or "")
        if m:
            ranks[h["id"]] = int(m.group(1))
    assert ranks.get(ids["rare"]) == 1, ranks
    for i in range(9):
        assert ranks.get(ids[f"d{i}"], 99) >= 2, ranks


@pytest.mark.asyncio
async def test_recall_k_bounds_only_ranking_k_independent(db, emb):
    """k bounds output size; ranking and confidence are computed before
    slicing, so they never depend on k."""
    from app.agents import retrieve

    # Same owner for both calls: k=8 serves all 5 seeded rows, so the
    # rehearsal bump lands uniformly and relative order is untouched
    # (id tie-breaks, F4, killed the old heap-order rationale for fresh
    # owners — and fresh owners reintroduce id tie-luck, which K=10
    # top-heaviness amplifies into runner-up flips). k is isolated by
    # serving everything first, then slicing.
    # Lexically distinct rows: identical term frequencies tie ts_rank.
    items = [
        {"name": "n0", "kind": "fact", "tags": ["deploy"],
         "content": "Deploy runbook master index deploy deploy deploy."},
        {"name": "n1", "kind": "fact", "tags": ["deploy"],
         "content": "Deploy runbook note beta with extra context words."},
        {"name": "n2", "kind": "fact", "tags": ["deploy"],
         "content": "Deploy checklist note gamma."},
        {"name": "n3", "kind": "fact", "tags": ["deploy"],
         "content": "Runbook note delta for staging deploys."},
        {"name": "n4", "kind": "fact", "tags": ["deploy"],
         "content": "Friday procedures note epsilon deploy runbook."},
    ]
    kw = dict(db=db, embedder=emb, session_id="s",
              tiers=None, settings=Settings())
    ow = f"rk_{uuid.uuid4().hex[:8]}"
    await seed(db, emb, ow, items)
    full = await retrieve.recall(query="deploy runbook", k=8, owner=ow,
                                 **kw)
    cut = await retrieve.recall(query="deploy runbook", k=1, owner=ow,
                                **kw)
    assert len(cut["hits"]) == 1
    assert cut["hits"][0]["summary"] == full["hits"][0]["summary"]
    assert cut["hits"][0]["score"] == full["hits"][0]["score"]
    assert cut["confidence"] == full["confidence"]
    assert cut["margin"] == full["margin"]


@pytest.mark.asyncio
async def test_replay_branch_orders_session(client, db, emb):
    ids = await seed(db, emb, OWNER, SEEDS)
    for i, (utt, mid) in enumerate([
        ("My name is Recallia", ids["name"]),
        ("Where is the checklist", ids["deploy"]),
    ]):
        await db.execute(
            "INSERT INTO memory_events (owner, session_id, turn, utterance, "
            "observer_verdict, scribe_action) VALUES (%s,%s,%s,%s,%s,%s)",
            (OWNER, "rsess", i, utt, Json({"keep": True}),
             Json({"op": "NEW", "memory_ids": [mid]})),
        )
    await client.post("/recall", json={  # recall events must not pollute replay
        "query": "noise", "session_id": "rsess", "owner": OWNER,
    }, headers=AUTH)
    r = await client.post("/recall", json={
        "query": "where were we?", "session_id": "rsess", "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert out["mode"] == "replay"
    assert out["abstain"] is False
    assert [t["turn"] for t in out["timeline"]] == [0, 1]
    assert all("noise" not in t["utterance"] for t in out["timeline"])


@pytest.mark.asyncio
async def test_replay_follows_turns_not_insert_order(client, db, emb):
    """Concurrency inversion: turn 1 committed before turn 0 — replay must
    still narrate 0 then 1 (logical order, never physical)."""
    ids = await seed(db, emb, OWNER, [
        {"name": "a", "content": "First the owner woke up.",
         "tags": ["morning"]},
        {"name": "b", "content": "Then the owner ran a mile.",
         "tags": ["run"]},
    ])
    for turn, (utt, mid) in [
        (1, ("Then the owner ran a mile.", ids["b"])),
        (0, ("First the owner woke up.", ids["a"])),
    ]:
        await db.execute(
            "INSERT INTO memory_events (owner, session_id, turn, utterance, "
            "observer_verdict, scribe_action) VALUES (%s,%s,%s,%s,%s,%s)",
            (OWNER, "inv", turn, utt, Json({"keep": True}),
             Json({"op": "NEW", "memory_ids": [mid]})),
        )
    r = await client.post("/recall", json={
        "query": "where were we?", "session_id": "inv", "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert out["mode"] == "replay"
    assert [t["turn"] for t in out["timeline"]] == [0, 1]


@pytest.mark.asyncio
async def test_associative_leg_case_insensitive(client, db, emb):
    """#FOOD in the query must fire the tag leg against stored 'food':
    the read path honors the same normalization as the write path."""
    await seed(db, emb, OWNER, [
        {"name": "ramen", "content": "The user adores midnight ramen.",
         "tags": ["food"]},
    ])
    r = await client.post("/recall", json={
        "query": "anything on #FOOD?", "session_id": "ci", "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert out["abstain"] is False
    ramen = [h for h in out["hits"] if "ramen" in h["summary"]]
    assert ramen, out["hits"]
    assert "tag #" in ramen[0]["why"], ramen[0]["why"]


@pytest.mark.asyncio
async def test_entity_leg_fires_on_subject_slot(client, db, emb):
    """Query words hitting scribe subject/object slots fire the entity
    leg — the same slots the linker wires, so graph and retrieval
    agree on what an entity is."""
    ids = await seed(db, emb, OWNER, [
        {"name": "vault", "content": "The vault combination was changed.",
         "tags": []},
    ])
    await db.execute(
        "UPDATE memories SET subject = 'vault' WHERE id = %s::uuid",
        (ids["vault"],))
    r = await client.post("/recall", json={
        "query": "vault status update", "session_id": "e1", "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert out["abstain"] is False, out
    hits = [h for h in out["hits"] if "vault" in h["summary"].lower()]
    assert hits, out["hits"]
    assert "entity #" in hits[0]["why"], hits[0]["why"]


@pytest.mark.asyncio
async def test_probe_case_insensitive(client, db, emb):
    await seed(db, emb, OWNER, [
        {"name": "ramen", "content": "The user adores midnight ramen.",
         "tags": ["food"]},
    ])
    r = await client.get(f"/probe?tag=%23FOOD&owner={OWNER}", headers=AUTH)
    got = {m["content"] for m in r.json()["memories"]}
    assert any("ramen" in c for c in got), got


@pytest.mark.asyncio
async def test_identity_and_probe_endpoints(client, db, emb):
    await seed(db, emb, OWNER, SEEDS)
    r = await client.get(f"/identity?owner={OWNER}", headers=AUTH)
    assert "Recallia" in r.json()["identity"][0]["content"]
    r = await client.get(f"/probe?tag=deploy&owner={OWNER}", headers=AUTH)
    got = {m["content"] for m in r.json()["memories"]}
    assert any("runbook" in c for c in got)
    assert not any("without review" in c for c in got)  # quarantined stays out


def test_card_truncates_at_line_boundary():
    """Dogfood night: the card cut mid-word ('#invoi', 'probe d'). Long
    cards now end at a newline with an honest marker, never mid-token."""
    from app.agents.retrieve import _card

    hits = [{
        "id": str(i), "tier": "knowledge", "kind": "fact",
        "summary": f"padded fact number {i} " + "x" * 120,
        "tags": [f"tag{i}"], "score": 1.0 - i * 0.01,
        "why": "QUESTION -> vector #1",
    } for i in range(30)]
    card = _card([], hits, False)
    assert card is not None and len(card) <= 1600 + 2
    assert card.endswith("\n…"), card[-20:]
    # every body line ends with ")": the cut kept whole lines only
    assert card[:-2].endswith(")"), card[-30:]


@pytest.mark.asyncio
async def test_recall_auth_and_shapes(client):
    body = {"query": "x", "session_id": "s", "owner": OWNER}
    assert (await client.post("/recall", json=body)).status_code == 401
    # Deliberately wrong token, built so no literal secret sits in source.
    bad = {"Authorization": "Bearer " + "x" * 12}
    assert (await client.post("/recall", json=body, headers=bad)).status_code == 401
    q = dict(body, query="   ")
    assert (await client.post("/recall", json=q, headers=AUTH)).status_code == 422


@pytest.mark.asyncio
async def test_recall_latency_smoke(client, db, emb):
    """100-row store answers fast. Bound is anti-regression (CI-safe), not
    the 300ms p95 acceptance — the measured number is what we judge."""
    import time

    vecs = []
    for i in range(5):
        v, _ = await emb.embed(f"Filler memory number {i} about routine topics.")
        vecs.append(v)
    for i in range(100):
        await db.execute(
            "INSERT INTO memories (owner, tier, kind, content, tags, salience, "
            "trust, source, embedding, embedding_model, hash) "
            "VALUES (%s,'knowledge','fact',%s,%s,0.5,'user_direct',%s,"
            "%s::vector,%s,%s)",
            (OWNER, f"Filler memory {i} about routine topic {i % 7}.",
             [f"t{i % 7}"], Json({"session": "perf", "turn": i}),
             pgvector_literal(vecs[i % 5]), emb.model_name, uuid.uuid4().hex),
        )
    t0 = time.monotonic()
    r = await client.post("/recall", json={
        "query": "routine topic 3", "session_id": "s", "owner": OWNER,
    }, headers=AUTH)
    dt = (time.monotonic() - t0) * 1000
    print(f"\nrecall p1 over 100 rows: {dt:.0f}ms")
    assert r.status_code == 200
    assert dt < 2000, f"recall too slow: {dt:.0f}ms"


@pytest.mark.asyncio
async def test_live_write_recall_roundtrip(client, db):
    """The 'it just knows' proof: live Meta write, then recall finds it."""
    r = await client.post("/write", json={
        "text": "My grandmother's soup needs extra thyme and a bay leaf.",
        "session_id": "r2live", "turn": 0, "owner": OWNER,
    }, headers=AUTH)
    assert r.status_code == 202
    for _ in range(120):
        n = await db.fetchval(
            "SELECT count(*) FROM memory_events WHERE session_id = 'r2live'"
        )
        if n and n >= 1:
            break
        await asyncio.sleep(2)
    r = await client.post("/recall", json={
        "query": "What does grandmother's soup need?", "session_id": "r2live",
        "owner": OWNER,
    }, headers=AUTH)
    out = r.json()
    assert out["abstain"] is False, out
    assert "thyme" in " ".join(h["summary"] for h in out["hits"])


@pytest.mark.asyncio
async def test_recall_story_narrates(client, db, emb):
    ids = await seed(db, emb, "rstory", [
        {"name": "lake", "content": "The lake cabin has a red canoe.",
         "tags": ["lake"]},
    ])
    r = await client.post("/recall", json={
        "query": "What is at the lake cabin?", "session_id": "rstory",
        "owner": "rstory",
    }, headers=AUTH)
    out = r.json()
    assert "QUESTION" in out["story"]
    assert "vector" in out["story"] or "lexical" in out["story"]
    assert "confidence" in out["story"]
    r = await client.post("/recall", json={
        "query": "Anything at all?", "session_id": "rstory",
        "owner": "rstory_empty",
    }, headers=AUTH)
    assert "abstained" in r.json()["story"]
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_reference_resolves_referent_from_session(client, db, emb):
    """REFERENCE resolution: 'that DB' points at the session episode naming
    it — overlap beats recency (target at turn 1, distractor at turn 2) —
    and recall answers from the resolved referent."""
    ow = f"rf_{uuid.uuid4().hex[:8]}"
    ids = await seed(db, emb, ow, [
        {"name": "garden", "tier": "episodic", "kind": "event",
         "session": "rfsess",
         "content": "The owner watered the garden beds at noon.",
         "tags": ["garden"]},
        {"name": "db", "tier": "episodic", "kind": "event",
         "session": "rfsess",
         "content": "We discussed using Postgres as the DB for the project.",
         "tags": ["db"]},
        {"name": "lunch", "tier": "episodic", "kind": "event",
         "session": "rfsess",
         "content": "Lunch was sandwiches on the porch.",
         "tags": ["lunch"]},
    ])
    r = await client.post("/recall", json={
        "query": "use that DB we discussed", "session_id": "rfsess",
        "owner": ow,
    }, headers=AUTH)
    out = r.json()
    assert out["cue"]["type"] == "REFERENCE"
    assert out["abstain"] is False, out
    assert out["referent"]["id"] == ids["db"], out["referent"]
    assert "that-N 'db'" in out["referent"]["match"]
    assert out["hits"][0]["id"] == ids["db"], out["hits"]
    assert "Postgres" in " ".join(h["summary"] for h in out["hits"])
    assert out["hits"][0]["why"].startswith("REFERENCE -> ")
    assert "referent" in out["story"]


@pytest.mark.asyncio
async def test_reference_pronoun_falls_back_to_most_recent(client, db, emb):
    """Bare 'do the same' carries no content words that match — the
    zero-evidence pronoun resolves to the most recent session episode."""
    ow = f"rf_{uuid.uuid4().hex[:8]}"
    ids = await seed(db, emb, ow, [
        {"name": "garden", "tier": "episodic", "kind": "event",
         "session": "rpsess",
         "content": "The owner watered the garden beds at noon.",
         "tags": ["garden"]},
        {"name": "lunch", "tier": "episodic", "kind": "event",
         "session": "rpsess",
         "content": "Lunch was sandwiches on the porch.",
         "tags": ["lunch"]},
    ])
    r = await client.post("/recall", json={
        "query": "Do the same as yesterday", "session_id": "rpsess",
        "owner": ow,
    }, headers=AUTH)
    out = r.json()
    assert out["cue"]["type"] == "REFERENCE"
    assert out["abstain"] is False, out
    assert out["referent"]["id"] == ids["lunch"], out["referent"]
    assert out["referent"]["match"] == "recency fallback"
    assert out["hits"][0]["id"] == ids["lunch"], out["hits"]


@pytest.mark.asyncio
async def test_reference_abstains_without_session_referent(client, db, emb):
    """No session episodes -> no referent -> honest abstain, even though the
    store holds a matching row (no fallthrough to general recall)."""
    ow = f"rf_{uuid.uuid4().hex[:8]}"
    await seed(db, emb, ow, [
        {"name": "db", "kind": "fact", "session": "other",
         "content": "Postgres is the project DB.", "tags": ["db"]},
    ])
    r = await client.post("/recall", json={
        "query": "use that DB we discussed", "session_id": "empty-sess",
        "owner": ow,
    }, headers=AUTH)
    out = r.json()
    assert out["cue"]["type"] == "REFERENCE"
    assert out["abstain"] is True, out
    assert out["hits"] == []
    assert out["confidence"] == 0.0
    assert out["card"] is None
    assert out["referent"] is None
    assert "no referent" in out["story"]


@pytest.mark.asyncio
async def test_reference_unmatched_definite_abstains(client, db, emb):
    """'that DB' with a gardening-only session: the definite names something
    never said here -> abstain rather than recency-guess."""
    ow = f"rf_{uuid.uuid4().hex[:8]}"
    await seed(db, emb, ow, [
        {"name": "garden", "tier": "episodic", "kind": "event",
         "session": "gsess",
         "content": "The owner watered the garden beds at noon.",
         "tags": ["garden"]},
    ])
    r = await client.post("/recall", json={
        "query": "use that DB we discussed", "session_id": "gsess",
        "owner": ow,
    }, headers=AUTH)
    out = r.json()
    assert out["cue"]["type"] == "REFERENCE"
    assert out["abstain"] is True, out
    assert out["hits"] == []
    assert out["referent"] is None


@pytest.mark.asyncio
async def test_reference_definite_needs_word_boundary(client, db, emb):
    """Manager review catch: hint matching must respect word boundaries —
    'that DB' must NOT match a row only containing 'redblueberries'
    (substring). No word 'db' anywhere -> honest abstain, no guessing."""
    ow = f"rf_{uuid.uuid4().hex[:8]}"
    await seed(db, emb, ow, [
        {"name": "trap", "tier": "episodic", "kind": "event",
         "session": "rfsess",
         "content": "We baked redblueberries into the pie.",
         "tags": ["baking"]},
    ])
    r = await client.post("/recall", json={
        "query": "use that DB we discussed", "session_id": "rfsess",
        "owner": ow,
    }, headers=AUTH)
    out = r.json()
    assert out["abstain"] is True, out
    assert out["hits"] == []
    assert out["referent"] is None


@pytest.mark.asyncio
async def test_reference_plural_those_resolves_all_matching(client, db, emb):
    """Plural 'those DBs' resolves to ALL matching recent candidates (both
    DB episodes, not just the top one), most-recent-first; the lunch
    distractor is excluded and recall answers from both referents."""
    ow = f"rf_{uuid.uuid4().hex[:8]}"
    ids = await seed(db, emb, ow, [
        {"name": "pg", "tier": "episodic", "kind": "event",
         "session": "plsess",
         "content": "We discussed using Postgres as the DB for the project.",
         "tags": ["db"]},
        {"name": "redis", "tier": "episodic", "kind": "event",
         "session": "plsess",
         "content": "We discussed using Redis as the DB cache layer.",
         "tags": ["db"]},
        {"name": "lunch", "tier": "episodic", "kind": "event",
         "session": "plsess",
         "content": "Lunch was sandwiches on the porch.",
         "tags": ["lunch"]},
    ])
    r = await client.post("/recall", json={
        "query": "use those DBs we discussed", "session_id": "plsess",
        "owner": ow,
    }, headers=AUTH)
    out = r.json()
    assert out["cue"]["type"] == "REFERENCE"
    assert out["abstain"] is False, out
    got = [rf["id"] for rf in out["referents"]]
    assert got == [ids["redis"], ids["pg"]], out["referents"]
    assert out["referent"]["id"] == ids["redis"]
    assert all("those-N 'dbs'" in rf["match"] for rf in out["referents"])
    assert "2 matches" in out["story"]
    assert "tie-break turn 1" in out["story"], out["story"]
    hits = {h["id"] for h in out["hits"]}
    assert {ids["pg"], ids["redis"]} <= hits, out["hits"]


@pytest.mark.asyncio
async def test_reference_plural_pronouns_resolve_all_recent(client, db, emb):
    """Zero-evidence plural pronouns ('they'/'them' with no content match)
    resolve to the whole recent window, most-recent-first — the plural
    analog of the singular recency baseline."""
    ow = f"rf_{uuid.uuid4().hex[:8]}"
    ids = await seed(db, emb, ow, [
        {"name": "garden", "tier": "episodic", "kind": "event",
         "session": "pnsess",
         "content": "The owner watered the garden beds at noon.",
         "tags": ["garden"]},
        {"name": "lunch", "tier": "episodic", "kind": "event",
         "session": "pnsess",
         "content": "Lunch was sandwiches on the porch.",
         "tags": ["lunch"]},
    ])
    for query in ("do they still work as we discussed",
                  "use them as we discussed"):
        r = await client.post("/recall", json={
            "query": query, "session_id": "pnsess", "owner": ow,
        }, headers=AUTH)
        out = r.json()
        assert out["cue"]["type"] == "REFERENCE", query
        assert out["abstain"] is False, (query, out)
        got = [rf["id"] for rf in out["referents"]]
        assert got == [ids["lunch"], ids["garden"]], (query, out)
        assert out["referent"]["id"] == ids["lunch"]
        assert all(rf["match"] == "recency fallback"
                   for rf in out["referents"])
        assert "2 matches" in out["story"], (query, out["story"])
        assert "tie-break turn 1" in out["story"], (query, out["story"])


@pytest.mark.asyncio
async def test_reference_tie_break_picks_most_recent_turn(client, db, emb):
    """Tied singular candidates (equal score, equal salience) resolve to
    the most recent turn, and the story names that turn."""
    ow = f"rf_{uuid.uuid4().hex[:8]}"
    ids = await seed(db, emb, ow, [
        {"name": "tune", "tier": "episodic", "kind": "event",
         "session": "tiesess",
         "content": "Postgres tuning notes for the project.",
         "tags": ["db"]},
        {"name": "backup", "tier": "episodic", "kind": "event",
         "session": "tiesess",
         "content": "Postgres backup notes for the project.",
         "tags": ["db"]},
    ])
    r = await client.post("/recall", json={
        "query": "use that DB we discussed", "session_id": "tiesess",
        "owner": ow,
    }, headers=AUTH)
    out = r.json()
    assert out["cue"]["type"] == "REFERENCE"
    assert out["abstain"] is False, out
    assert out["referent"]["id"] == ids["backup"], out["referent"]
    assert out["referent"]["match"] == "that-N 'db'"
    assert out["referent"]["turn"] == 1
    assert [rf["id"] for rf in out["referents"]] == [ids["backup"]]
    assert "tie-break turn 1" in out["story"], out["story"]
    assert out["hits"][0]["id"] == ids["backup"], out["hits"]


@pytest.mark.asyncio
async def test_reference_plural_unmatched_definite_abstains(client, db, emb):
    """'those DBs' with a gardening-only session: the plural definite still
    denotes — abstain rather than returning the whole window."""
    ow = f"rf_{uuid.uuid4().hex[:8]}"
    await seed(db, emb, ow, [
        {"name": "garden", "tier": "episodic", "kind": "event",
         "session": "pgsess",
         "content": "The owner watered the garden beds at noon.",
         "tags": ["garden"]},
    ])
    r = await client.post("/recall", json={
        "query": "use those DBs we discussed", "session_id": "pgsess",
        "owner": ow,
    }, headers=AUTH)
    out = r.json()
    assert out["cue"]["type"] == "REFERENCE"
    assert out["abstain"] is True, out
    assert out["hits"] == []
    assert out["referent"] is None
    assert out["referents"] == []
    assert "no referent" in out["story"]


@pytest.mark.asyncio
async def test_concept_boost_promotes_only_matches(db, emb, monkeypatch):
    """Concept leg is boost-only with exact RRF math: the stubbed
    concept 'business' FTS-matches row A alone (rank 1), so A gains
    exactly 1/(60+1) and a 'concept #1' leg while B is untouched.
    No LLM in tests: query_concepts is stubbed, flag forced on."""
    from app.agents import retrieve
    ow = f"rc_{uuid.uuid4().hex[:8]}"
    ids = await seed(db, emb, ow, [
        {"name": "a", "kind": "fact",
         "content": "Business archive rules are strict."},
        {"name": "b", "kind": "fact",
         "content": "Zebra migration patterns shift."},
    ])
    s = Settings()
    s.recall_concepts = True
    kw = dict(db=db, embedder=emb, owner=ow, session_id="s", k=8,
              tiers=None, settings=s)

    async def noboost(q):
        return []

    async def biz(q):
        return ["business"]

    monkeypatch.setattr(retrieve, "query_concepts", noboost)
    base = await retrieve.recall(query="draft a quotation", **kw)
    monkeypatch.setattr(retrieve, "query_concepts", biz)
    boosted = await retrieve.recall(query="draft a quotation", **kw)
    bb = {h["id"]: h for h in base["hits"]}
    bo = {h["id"]: h for h in boosted["hits"]}
    assert set(bb) == set(bo) == set(ids.values())
    assert "concept #1" in bo[ids["a"]]["why"], bo[ids["a"]]
    assert "concept" not in bo[ids["b"]]["why"], bo[ids["b"]]
    # F5: concept leg corroborates at 0.2, K=10 (weighted top-heavy RRF).
    assert bo[ids["a"]]["score"] == pytest.approx(
        bb[ids["a"]]["score"] + 0.2 / 11, rel=2e-2)
    assert bo[ids["b"]]["score"] == pytest.approx(
        bb[ids["b"]]["score"], rel=1e-9)


@pytest.mark.asyncio
async def test_lexical_or_fallback_when_and_is_void(db, emb):
    """F3: one bad lexeme ('0.6B' splits to '0.6'&'b', stored model
    name is one glued compound) voids the AND — the OR tail must
    still surface lexical evidence with the best row first."""
    from app.agents import retrieve
    ow = f"rc_{uuid.uuid4().hex[:8]}"
    query = "What first-packet latency does the Qwen3-TTS 0.6B variant achieve?"
    ids = await seed(db, emb, ow, [
        {"name": "spec",
         "content": "Qwen3-TTS-12Hz-0.6B variant achieves 97ms "
                    "first-packet latency with 19ms LM time."},
        {"name": "other",
         "content": "Qwen3-TTS uses dual-track design with semantic tokenizer."},
    ])
    void = await db.fetch(
        "SELECT id FROM memories WHERE owner = %s AND valid_to IS NULL "
        "AND to_tsvector('english', content) @@ "
        "plainto_tsquery('english', %s)",
        (ow, query))
    assert void == [], "premise: AND matches nothing"
    s = Settings()
    s.recall_concepts = False
    out = await retrieve.recall(query=query, db=db, embedder=emb, owner=ow,
                                session_id="s", k=8, tiers=None, settings=s)
    hits = {h["id"]: h for h in out["hits"]}
    assert ids["spec"] in hits
    assert "lexical #" in hits[ids["spec"]]["why"], hits[ids["spec"]]
    assert out["hits"][0]["id"] == ids["spec"], [
        (h["id"], h["why"]) for h in out["hits"]]


def test_weighted_rrf_peak_beats_breadth():
    """F5 (Balancing the Blend weakest-link): vector#1+lexical#1 must
    beat vector#53+lexical#5+entity#2+concept#5 — the exact live NUST
    near-tie. Pure function, no DB."""
    from app.agents.retrieve import _rrf
    rows = [
        {"id": "peak", "leg": "v", "rnk": 1},
        {"id": "peak", "leg": "f", "rnk": 1},
        {"id": "peak", "leg": "e", "rnk": 7},
        {"id": "broad", "leg": "v", "rnk": 53},
        {"id": "broad", "leg": "f", "rnk": 5},
        {"id": "broad", "leg": "e", "rnk": 2},
        {"id": "broad", "leg": "c", "rnk": 5},
    ]
    fused = _rrf(rows)
    assert fused["peak"]["score"] > fused["broad"]["score"], fused
    # Equal weights lose it (the old disease): 0.0477 < 0.0557.
    plain = sum(1.0 / (60 + r) for r in (1, 1, 7))
    plain_broad = sum(1.0 / (60 + r) for r in (53, 5, 2, 5))
    assert plain < plain_broad


@pytest.mark.asyncio
async def test_concepts_memoized_per_query(db, emb, monkeypatch):
    """F4: identical queries expand identically — the clerk is asked
    once no matter how often recall runs (temp is already 0 and it
    still varied: 4 lists in 5 live calls). No LLM in tests."""
    from app.agents import retrieve
    calls = []

    class _Prov:
        name = "stub"
        async def close(self):
            pass

    async def _resolve():
        calls.append(1)
        return _Prov()

    class _Raw:
        text = "alpha, beta, gamma"
        resampled = False
        prompt_tokens = 0
        completion_tokens = 0

    async def _complete(provider, messages, **kw):
        return _Raw()

    import app.providers.resolve as pr
    import app.providers.base as pb
    monkeypatch.setattr(pr, "resolve_provider", _resolve)
    monkeypatch.setattr(pb, "complete_resilient", _complete)
    monkeypatch.setattr(retrieve, "_CONCEPT_MEMO", {})
    q = f"memo probe {uuid.uuid4().hex[:8]}"
    first = await retrieve.query_concepts(q)
    second = await retrieve.query_concepts("  " + q.upper() + "  ")
    assert first == second == ["alpha", "beta", "gamma"]
    assert len(calls) == 1, calls


@pytest.mark.asyncio
async def test_recall_order_stable_across_runs(db, emb, monkeypatch):
    """F4 guard: same query twice yields identical hit order (id
    tie-breaks terminate every leg ordering; memo pins concepts)."""
    from app.agents import retrieve
    ow = f"rc_{uuid.uuid4().hex[:8]}"
    await seed(db, emb, ow, [
        {"name": "a", "content": "Zebra migration patterns shift yearly."},
        {"name": "b", "content": "Zebra migration routes cross rivers."},
        {"name": "c", "content": "Zebra herd counts grow steadily."},
    ])
    s = Settings()
    s.recall_concepts = True

    async def fixed(q):
        return ["zebra", "migration"]

    monkeypatch.setattr(retrieve, "query_concepts", fixed)
    kw = dict(db=db, embedder=emb, owner=ow, session_id="s", k=8,
              tiers=None, settings=s)
    first = [h["id"] for h in (await retrieve.recall(
        query="zebra migration shifting", **kw))["hits"]]
    second = [h["id"] for h in (await retrieve.recall(
        query="zebra migration shifting", **kw))["hits"]]
    assert first == second and len(first) == 3, (first, second)

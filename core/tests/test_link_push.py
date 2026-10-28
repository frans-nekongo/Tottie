"""Linking, pushed to the limit: the battery the user demanded.

Not safe small cases — concurrency, quarantine poisoning, cross-owner
leaks, mush at scale, burst load, and the user's own live trio
(cheese / petite-women / vegetarian) as a regression test. Deterministic
stub-Scribe (real DB + real embedder, no LLM) except the one live trio
run, which asserts only what is deterministic about LLM output and
conditional stories otherwise.
"""
import asyncio
import re
import uuid

import pytest

from app.agents import relink as rl_agent
from app.agents import scribe
from app.agents.observer import Observation
from app.agents.reconcile import TAG_LINK_CAP
from app.config import Settings
from app.embeddings import Embedder
from app.queue import WorkerTurn
from tests.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
TURN_RE = re.compile(r"turn (\d+) -> turn (\d+)")


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


def _turn(text, session, turn, owner, trust="user_direct"):
    return WorkerTurn(text=text, session_id=session, turn=turn, owner=owner,
                      trust=trust, origin=None, client_event_id=uuid.uuid4().hex)


def _obs(content, tags, kind="preference", salience=0.8, subject=None,
         predicate=None, obj=None):
    return Observation(
        keep=True, salience=salience, surprise=0.9,
        candidates=[{"kind": kind, "tier": "knowledge", "subject": subject,
                     "predicate": predicate, "object": obj, "content": content,
                     "tags": tags, "principle": None}],
        verdict="keep", provider="stub")


async def _ids_by_content(db, owner):
    rows = await db.fetch(
        "SELECT id, content FROM memories WHERE owner = %s", (owner,))
    return {r["content"]: str(r["id"]) for r in rows}


@pytest.mark.asyncio
async def test_concurrent_chain_never_runs_backwards(db, emb):
    """8 concurrent same-session writes: every temporal arrow must run
    low-turn -> high-turn (the live turn-1 -> turn-0 backwards bug), and
    relink must then complete the chain to exactly n-1 forward edges."""
    ow = f"lp_{uuid.uuid4().hex[:8]}"
    texts = [f"Concurrent memory number {i} about utterly distinct "
             f"topic {w}."
             for i, w in enumerate(["harbors", "quilts", "volcanoes",
                                    "trombones", "canyons", "lanterns",
                                    "glaciers", "orchards"])]
    await asyncio.gather(*[
        scribe.persist(db=db, embedder=emb, turn=_turn(t, ow, i, ow),
                       obs=_obs(t, [f"push{i}"]))
        for i, t in enumerate(texts)
    ])
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (ow,))
    assert n == 8, f"burst lost rows: {n}"
    edges = await db.fetch(
        "SELECT reason FROM memory_links WHERE owner = %s "
        "AND relation = 'temporal'",
        (ow,),
    )
    for e in edges:
        m = TURN_RE.search(e["reason"] or "")
        assert m, f"temporal edge lost its story: {e['reason']}"
        assert int(m.group(1)) < int(m.group(2)), \
            f"BACKWARDS chain edge: {e['reason']}"
    await rl_agent.relink(db, ow)
    fwd = await db.fetch(
        "SELECT src, dst, reason FROM memory_links WHERE owner = %s "
        "AND relation = 'temporal'",
        (ow,),
    )
    order = await db.fetch(
        "SELECT id, source FROM memories WHERE owner = %s", (ow,))
    turn_of = {str(r["id"]): r["source"]["turn"] for r in order}
    id_of = {t: i for i, t in turn_of.items()}
    for e in fwd:
        assert turn_of[str(e["src"])] < turn_of[str(e["dst"])], e["reason"]
    # relink guarantees the canonical linked list exists; concurrent twins
    # may add extra forward shortcuts, never backwards lies
    pairs = {(str(e["src"]), str(e["dst"])) for e in fwd}
    for i in range(1, 8):
        assert (id_of[i - 1], id_of[i]) in pairs, \
            f"canonical pair turn {i - 1} -> turn {i} missing"


@pytest.mark.asyncio
async def test_turn_gap_chain_carries_real_turns(db, emb):
    ow = f"lp_{uuid.uuid4().hex[:8]}"
    for t in (0, 1, 5):
        text = f"Gap memory at turn {t}."
        await scribe.persist(db=db, embedder=emb, turn=_turn(text, ow, t, ow),
                             obs=_obs(text, [f"g{t}"]))
    edges = await db.fetch(
        "SELECT src, dst, reason FROM memory_links WHERE owner = %s "
        "AND relation = 'temporal' ORDER BY reason",
        (ow,),
    )
    assert [e["reason"] for e in edges] == [
        "session order: turn 0 -> turn 1",
        "session order: turn 1 -> turn 5",
    ], edges


@pytest.mark.asyncio
async def test_popular_tag_capped_prefers_salient(db, emb):
    """12 rows share 'food': the 13th links at most TAG_LINK_CAP of them,
    and the winners are the most salient — no explosion, no lottery."""
    ow = f"lp_{uuid.uuid4().hex[:8]}"
    topics = [
        "Owner buys green apples every Tuesday at the corner market.",
        "Owner bakes sourdough when the kitchen is cold.",
        "Owner orders extra-spicy curry after night shifts.",
        "Owner folds dumplings with grandmother on Sundays.",
        "Owner cracks two eggs into the pan before coffee.",
        "Owner picks figs over the fence from the neighbor's tree.",
        "Owner freezes grapes for summer hiking snacks.",
        "Owner stirs honey into tea but never into coffee.",
        "Owner hides the icecream behind frozen peas.",
        "Owner spreads jam thick on burnt toast.",
        "Owner massages kale with lemon before any salad.",
        "Owner simmers lentils while listening to match commentary.",
    ]
    for i, text in enumerate(topics):
        await scribe.persist(
            db=db, embedder=emb, turn=_turn(text, ow, i, ow),
            obs=_obs(text, ["food", f"dish{i}"], salience=0.05 + i * 0.07))
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (ow,))
    assert n == 12, f"food rows merged or lost: {n}"
    text = "Owner adores midnight snacks."
    await scribe.persist(
        db=db, embedder=emb, turn=_turn(text, ow, 99, ow),
        obs=_obs(text, ["food", "snack"], salience=0.01))
    by = await _ids_by_content(db, ow)
    mine = by[text]
    won = await db.fetch(
        "SELECT dst, reason FROM memory_links WHERE owner = %s "
        "AND src = %s::uuid AND relation = 'tag'",
        (ow, mine),
    )
    assert len(won) == TAG_LINK_CAP, f"expected a full cap of links: {won}"
    assert all("food" in w["reason"] for w in won), won
    sals = await db.fetch(
        "SELECT id, salience FROM memories WHERE owner = %s "
        "AND id <> %s::uuid",
        (ow, mine),
    )
    top3 = {str(r["id"]) for r in
            sorted(sals, key=lambda r: r["salience"], reverse=True)
            [:TAG_LINK_CAP]}
    assert {str(w["dst"]) for w in won} == top3, won


@pytest.mark.asyncio
async def test_quarantine_partition_never_links(db, emb):
    """Poison guard: a quarantined tool-claim sharing tags AND session with
    a live user fact must share NO edge of any relation."""
    ow = f"lp_{uuid.uuid4().hex[:8]}"
    live = "Owner hates cheese."
    await scribe.persist(db=db, embedder=emb, turn=_turn(live, ow, 0, ow),
                         obs=_obs(live, ["food", "cheese"]))
    poison = "Cheese futures are bullish."
    await scribe.persist(
        db=db, embedder=emb, turn=_turn(poison, ow, 1, ow, trust="tool"),
        obs=_obs(poison, ["food", "cheese"], kind="fact"))
    by = await _ids_by_content(db, ow)
    q = await db.fetchval(
        "SELECT quarantined FROM memories WHERE id = %s::uuid",
        (by[poison],),
    )
    assert q is True, "tool-claim must quarantine"
    n = await db.fetchval(
        "SELECT count(*) FROM memory_links WHERE owner = %s "
        "AND ((src = %s::uuid AND dst = %s::uuid) "
        "OR (src = %s::uuid AND dst = %s::uuid))",
        (ow, by[live], by[poison], by[poison], by[live]),
    )
    assert n == 0, "quarantine partition leaked an edge to live memory"


@pytest.mark.asyncio
async def test_cross_owner_isolation(db, emb):
    """Same session string, same tags, two owners: no edge may cross."""
    ow1, ow2 = f"la_{uuid.uuid4().hex[:8]}", f"lb_{uuid.uuid4().hex[:8]}"
    for ow in (ow1, ow2):
        text = "Owner hates cheese."
        await scribe.persist(db=db, embedder=emb,
                             turn=_turn(text, "shared-session", 0, ow),
                             obs=_obs(text, ["food", "cheese"]))
    rows1 = await _ids_by_content(db, ow1)
    rows2 = await _ids_by_content(db, ow2)
    cross = await db.fetchval(
        "SELECT count(*) FROM memory_links WHERE "
        "(src = %s::uuid AND dst = %s::uuid) "
        "OR (src = %s::uuid AND dst = %s::uuid)",
        (next(iter(rows1.values())), next(iter(rows2.values())),
         next(iter(rows2.values())), next(iter(rows1.values()))),
    )
    assert cross == 0, "an edge crossed the owner boundary"


@pytest.mark.asyncio
async def test_tag_case_whitespace_still_links(db, emb):
    """'Food ' vs 'food' vs 'FOOD' is the same token: must link, and the
    stored tags come out normalized."""
    ow = f"lp_{uuid.uuid4().hex[:8]}"
    a, b = "Owner hates cheese.", "Owner is vegetarian."
    await scribe.persist(db=db, embedder=emb, turn=_turn(a, ow, 0, ow),
                         obs=_obs(a, ["Food ", " DAIRY", ""]))
    await scribe.persist(db=db, embedder=emb, turn=_turn(b, ow, 1, ow),
                         obs=_obs(b, ["FOOD", "diet"]))
    by = await _ids_by_content(db, ow)
    stored = await db.fetch(
        "SELECT content, tags FROM memories WHERE owner = %s", (ow,))
    expect = {a: ["food", "dairy"], b: ["food", "diet"]}
    for r in stored:
        assert r["tags"] == expect[r["content"]], r
    tag = await db.fetch(
        "SELECT reason FROM memory_links WHERE owner = %s "
        "AND src = %s::uuid AND dst = %s::uuid AND relation = 'tag'",
        (ow, by[b], by[a]),
    )
    assert tag and "food" in tag[0]["reason"], \
        "case/whitespace variants missed their must-link"


@pytest.mark.asyncio
async def test_kind_mush_at_scale(db, emb):
    """10 rows tagged only with the kind-name: zero TAG edges among them
    (temporal chain still allowed — sequence is real, mush is not)."""
    ow = f"lp_{uuid.uuid4().hex[:8]}"
    topics = [
        "Owner prefers window seats on night flights.",
        "Owner boils pasta exactly one minute less than the box says.",
        "Owner keeps a paper map of Lisbon taped inside the wardrobe.",
        "Owner hums basslines while waiting for elevators.",
        "Owner photographs rusted padlocks on old bridges.",
        "Owner sorts coins by year before rolling them.",
        "Owner waters the fern only when it droops dramatically.",
        "Owner reads ferry timetables for fun on Sundays.",
        "Owner sharpens pencils with a pocket knife.",
        "Owner names every houseplant after jazz musicians.",
    ]
    for i, text in enumerate(topics):
        await scribe.persist(db=db, embedder=emb, turn=_turn(text, ow, i, ow),
                             obs=_obs(text, ["preference"]))
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (ow,))
    assert n == 10, f"mush rows merged or lost: {n}"
    mush = await db.fetchval(
        "SELECT count(*) FROM memory_links WHERE owner = %s "
        "AND relation = 'tag'",
        (ow,),
    )
    assert mush == 0, f"kind-name mush linked at scale: {mush}"


@pytest.mark.asyncio
async def test_supersede_edge_tells_replacement(db, emb):
    ow = f"lp_{uuid.uuid4().hex[:8]}"
    await scribe.persist(
        db=db, embedder=emb, turn=_turn("I eat meat.", ow, 0, ow),
        obs=_obs("Owner eats meat.", ["diet"], kind="fact",
                 subject="user", predicate="diet", obj="meat-eater"))
    await scribe.persist(
        db=db, embedder=emb, turn=_turn("I'm vegetarian now.", ow, 1, ow),
        obs=_obs("Owner is vegetarian.", ["diet"], kind="fact",
                 subject="user", predicate="diet", obj="vegetarian"))
    rows = await db.fetch(
        "SELECT id, content, valid_to FROM memories WHERE owner = %s "
        "ORDER BY created_at",
        (ow,),
    )
    assert len(rows) == 2 and rows[0]["valid_to"] is not None
    assert rows[1]["valid_to"] is None
    edge = await db.fetchrow(
        "SELECT relation, reason FROM memory_links WHERE owner = %s "
        "AND src = %s::uuid AND dst = %s::uuid",
        (ow, rows[1]["id"], rows[0]["id"]),
    )
    assert edge and edge["relation"] == "supersedes", edge
    assert "replaced" in (edge["reason"] or ""), edge


@pytest.mark.asyncio
async def test_duplicate_turn_writes_once(db, emb):
    """Same (session, turn, utterance) fired twice concurrently: one memory
    row, one event — the turn race resolves, never dupes."""
    ow = f"lp_{uuid.uuid4().hex[:8]}"
    text = "Owner hates cheese."
    res = await asyncio.gather(*[
        scribe.persist(db=db, embedder=emb, turn=_turn(text, ow, 0, ow),
                       obs=_obs(text, ["food", "cheese"]))
        for _ in range(2)
    ])
    assert sorted(res)[0].startswith("NEW"), res
    assert sorted(res)[1].startswith("SKIP"), res
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (ow,))
    assert n == 1, f"turn race duped rows: {n}"
    e = await db.fetchval(
        "SELECT count(*) FROM memory_events WHERE session_id = %s", (ow,))
    assert e == 1, f"turn race duped events: {e}"


@pytest.mark.asyncio
async def test_burst_sixty_bounded(db, emb):
    """Load: 60 concurrent writes — no loss, no dupes, links bounded,
    every edge storied. Relink then completes the chain exactly."""
    ow = f"lpb_{uuid.uuid4().hex[:8]}"
    bases = [
        "The cellar keeps red wine at sixteen degrees.",
        "Morning sprints happen at the old stadium.",
        "Quarterly taxes are filed through the bronze portal.",
        "The violin needs new strings before winter.",
        "Server backups rotate every third Sunday.",
        "The garden grows heirloom tomatoes and basil.",
        "Passport renewals take six weeks by post.",
        "The cat prefers salmon over chicken.",
        "Mortgage rates are reviewed each spring.",
        "The telescope lens was cleaned in March.",
        "Bread rises best near the warm window.",
        "The marathon route passes the lighthouse.",
        "Invoices go out on the first Monday.",
        "The piano was tuned after the move.",
        "Passwords rotate on the equinox.",
        "The attic stores childhood photo albums.",
        "Ferry tickets cost extra on holidays.",
        "The dog barks at the mail van daily.",
        "Insurance renews automatically in June.",
        "The clock chimes thirteen times daily.",
    ]
    topics = [f"{b} (note {k})" for k in range(3) for b in bases]

    async def one(i):
        # fully unique tags: near-dupe contents must still stay NEW
        # (no shared-tag anchor, null SP) rather than merge
        return await scribe.persist(
            db=db, embedder=emb, turn=_turn(topics[i], ow, i, ow),
            obs=_obs(topics[i], [f"u{i}"]))

    ops = await asyncio.gather(*[one(i) for i in range(60)])
    assert all(o.startswith(("NEW", "RAW")) for o in ops), ops
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (ow,))
    assert n == 60, f"burst lost or duped rows: {n}"
    links = await db.fetchval(
        "SELECT count(*) FROM memory_links WHERE owner = %s", (ow,))
    assert links <= 60, f"link explosion: {links}"
    bare = await db.fetchval(
        "SELECT count(*) FROM memory_links WHERE owner = %s "
        "AND (reason IS NULL OR reason = '')",
        (ow,),
    )
    assert bare == 0
    await rl_agent.relink(db, ow)
    fwd = await db.fetch(
        "SELECT src, dst FROM memory_links WHERE owner = %s "
        "AND relation = 'temporal'",
        (ow,),
    )
    order = await db.fetch(
        "SELECT id, source FROM memories WHERE owner = %s", (ow,))
    id_of = {r["source"]["turn"]: str(r["id"]) for r in order}
    pairs = {(str(e["src"]), str(e["dst"])) for e in fwd}
    missing = [i for i in range(1, 60)
               if (id_of[i - 1], id_of[i]) not in pairs]
    assert not missing, f"relink left chain gaps at turns {missing}"


@pytest.mark.asyncio
async def test_own_kind_overlap_never_links(db, emb):
    """Emergent-kind mush guard: rows sharing only their own kind word
    ('habit'/'habit') form no tag edge, even though the raw tags match."""
    ow = f"lp_{uuid.uuid4().hex[:8]}"
    a = "Owner jogs every morning at dawn."
    b = "Owner meditates every evening at dusk."
    await scribe.persist(db=db, embedder=emb, turn=_turn(a, ow, 0, ow),
                         obs=_obs(a, ["habit", "running"], kind="habit"))
    await scribe.persist(db=db, embedder=emb, turn=_turn(b, ow, 1, ow),
                         obs=_obs(b, ["habit", "calm"], kind="habit"))
    by = await _ids_by_content(db, ow)
    tag = await db.fetch(
        "SELECT reason FROM memory_links WHERE owner = %s "
        "AND src = %s::uuid AND dst = %s::uuid AND relation = 'tag'",
        (ow, by[b], by[a]),
    )
    assert not tag, f"own-kind overlap linked: {tag}"


@pytest.mark.asyncio
async def test_contiguity_follows_turns_not_commit_order(db):
    """Winner's before/after path must narrate logical turns even when rows
    committed out of order (the created_at lie, same class as the
    backwards temporal chain)."""
    from psycopg.types.json import Json

    from app.agents import retrieve as ret_agent

    ow = f"lp_{uuid.uuid4().hex[:8]}"
    ids = {}
    # turn 2 committed first (oldest created_at), turn 0 last
    for turn, stamp in [(2, "2026-01-01"), (1, "2026-02-01"),
                        (0, "2026-03-01")]:
        row = await db.execute_returning(
            "INSERT INTO memories (owner, tier, kind, content, tags, source, "
            "created_at) VALUES (%s, 'episodic', 'event', %s, %s, %s, %s) "
            "RETURNING id",
            (ow, f"Episode at turn {turn}.", [f"ep{turn}"],
             Json({"session": ow, "turn": turn}), stamp),
        )
        ids[turn] = str(row["id"])
    winner = await db.fetchrow(
        "SELECT id, source, created_at FROM memories WHERE id = %s::uuid",
        (ids[1],),
    )
    path = await ret_agent._contiguity(db, ow, dict(winner))
    assert path == [ids[0], ids[1], ids[2]], path


@pytest.mark.asyncio
async def test_live_trio_no_mush(client, db):
    """The user's own session through the live pipe: cheese must never
    TAG-link to petite-women, and whatever tag edges the LLM's tags do
    produce must carry their story. Runs relink first so the assertion
    covers the completed graph, not a racing queue."""
    ow = f"lpt_{uuid.uuid4().hex[:8]}"
    for i, text in enumerate(["I hate cheese.", "I like petite women.",
                              "I am vegetarian."]):
        r = await client.post("/write", json={
            "text": text, "session_id": ow, "turn": i, "owner": ow,
            "source": {"trust": "user_direct"},
        }, headers=AUTH)
        assert r.status_code == 202
    rows = []
    for _ in range(90):
        rows = await db.fetch(
            "SELECT id, content FROM memories WHERE owner = %s "
            "AND valid_to IS NULL",
            (ow,),
        )
        if len(rows) >= 3:
            break
        await asyncio.sleep(2)
    assert len(rows) >= 3, "live pipe kept fewer than the trio"
    await rl_agent.relink(db, ow)
    by = {r["content"]: str(r["id"]) for r in rows}
    cheese = next(v for k, v in by.items() if "cheese" in k)
    petite = next(v for k, v in by.items() if "petite" in k)
    mush = await db.fetch(
        "SELECT relation, reason FROM memory_links WHERE owner = %s "
        "AND relation = 'tag' AND ((src = %s::uuid AND dst = %s::uuid) "
        "OR (src = %s::uuid AND dst = %s::uuid))",
        (ow, cheese, petite, petite, cheese),
    )
    assert not mush, f"live LLM tags mushed cheese into petite: {mush}"
    bare = await db.fetchval(
        "SELECT count(*) FROM memory_links WHERE owner = %s "
        "AND (reason IS NULL OR reason = '')",
        (ow,),
    )
    assert bare == 0

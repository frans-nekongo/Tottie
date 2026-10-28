"""Linking v2, adversarial: the user's own callouts as test cases.

Deterministic stub-Scribe (real DB + real embedder, no LLM) except the one
live end-to-end cheese/vegetarian run and the burst stress. Failures here
mean the graph lies: missed obvious links or invented mush ones.
"""
import asyncio
import uuid

import pytest

from app.agents import scribe
from app.agents.observer import Observation
from app.config import Settings
from app.embeddings import Embedder
from app.queue import WorkerTurn
from tests.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


def _turn(text, session, turn, owner, trust="user_direct"):
    return WorkerTurn(text=text, session_id=session, turn=turn, owner=owner,
                      trust=trust, origin=None, client_event_id=uuid.uuid4().hex)


def _obs(content, tags, kind="preference"):
    return Observation(
        keep=True, salience=0.8, surprise=0.9,
        candidates=[{"kind": kind, "tier": "knowledge", "subject": None,
                     "predicate": None, "object": None, "content": content,
                     "tags": tags, "principle": None}],
        verdict="keep", provider="stub")


async def _links_between(db, owner, a, b):
    return await db.fetch(
        "SELECT relation, reason FROM memory_links WHERE owner = %s "
        "AND ((src = %s::uuid AND dst = %s::uuid) "
        "OR (src = %s::uuid AND dst = %s::uuid))",
        (owner, a, b, b, a),
    )


@pytest.mark.asyncio
async def test_kind_tags_never_link(db, emb):
    """The cheese-petite mush: overlap on 'preference' alone must not link."""
    ow = f"lk_{uuid.uuid4().hex[:8]}"
    await scribe.persist(db=db, embedder=emb,
                         turn=_turn("I hate cheese.", ow, 0, ow),
                         obs=_obs("I hate cheese.", ["food", "cheese", "preference"]))
    await scribe.persist(db=db, embedder=emb,
                         turn=_turn("I like petite women.", ow, 1, ow),
                         obs=_obs("I like petite women.", ["preference", "attraction"]))
    rows = await db.fetch(
        "SELECT id, content FROM memories WHERE owner = %s", (ow,))
    by = {r["content"]: str(r["id"]) for r in rows}
    links = await _links_between(db, ow, by["I hate cheese."],
                                 by["I like petite women."])
    assert "tag" not in {l["relation"] for l in links}, \
        f"kind-name overlap linked unrelated rows: {links}"


@pytest.mark.asyncio
async def test_category_overlap_links_with_reason(db, emb):
    """The cheese-vegetarian must-link: shared 'food' carries its story."""
    ow = f"lk_{uuid.uuid4().hex[:8]}"
    await scribe.persist(db=db, embedder=emb,
                         turn=_turn("I hate cheese.", ow, 0, ow),
                         obs=_obs("I hate cheese.", ["food", "cheese"]))
    await scribe.persist(db=db, embedder=emb,
                         turn=_turn("I am vegetarian.", "other", 0, ow),
                         obs=_obs("I am vegetarian.", ["food", "diet"]))
    rows = await db.fetch(
        "SELECT id, content FROM memories WHERE owner = %s", (ow,))
    by = {r["content"]: str(r["id"]) for r in rows}
    links = await _links_between(db, ow, by["I hate cheese."],
                                 by["I am vegetarian."])
    tag = [l for l in links if l["relation"] == "tag"]
    assert tag, "shared category tag produced no link"
    assert "food" in tag[0]["reason"], tag


@pytest.mark.asyncio
async def test_temporal_chain_before_after(db, emb):
    """Linked list: each memory points at the previous one in its session."""
    ow = f"lk_{uuid.uuid4().hex[:8]}"
    for i, (text, tags) in enumerate([
        ("First thing.", ["aaa"]), ("Second thing.", ["bbb"]),
        ("Third thing.", ["ccc"]),
    ]):
        await scribe.persist(db=db, embedder=emb,
                             turn=_turn(text, ow, i, ow),
                             obs=_obs(text, tags))
    rows = await db.fetch(
        "SELECT id, content FROM memories WHERE owner = %s", (ow,))
    by = {r["content"]: str(r["id"]) for r in rows}
    links = await db.fetch(
        "SELECT src, dst, reason FROM memory_links WHERE owner = %s "
        "AND relation = 'temporal'",
        (ow,),
    )
    assert len(links) == 2, f"chain must be exactly n-1, got {links}"
    fwd = {str(l["src"]): str(l["dst"]) for l in links}
    assert fwd[by["Third thing."]] == by["Second thing."]
    assert fwd[by["Second thing."]] == by["First thing."]
    assert all("turn" in l["reason"] and "session" in l["reason"]
               for l in links), links


@pytest.mark.asyncio
async def test_every_link_has_reason(db, emb):
    ow = f"lk_{uuid.uuid4().hex[:8]}"
    await scribe.persist(db=db, embedder=emb,
                         turn=_turn("I hate cheese.", ow, 0, ow),
                         obs=_obs("I hate cheese.", ["food", "cheese"]))
    await scribe.persist(db=db, embedder=emb,
                         turn=_turn("I am vegetarian.", ow, 1, ow),
                         obs=_obs("I am vegetarian.", ["food", "diet"]))
    n = await db.fetchval(
        "SELECT count(*) FROM memory_links WHERE owner = %s "
        "AND (reason IS NULL OR reason = '')",
        (ow,),
    )
    assert n == 0, "every new link must carry its story"


@pytest.mark.asyncio
async def test_cheese_vegetarian_live_pipeline(client, db):
    """Full live pipe, the user's session: both kept AND connected."""
    ow = f"lkl_{uuid.uuid4().hex[:8]}"
    for i, text in enumerate(["I hate cheese.", "I am vegetarian."]):
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
        if len(rows) >= 2:
            break
        await asyncio.sleep(2)
    assert len(rows) >= 2, "live pipe kept fewer than both facts"
    by = {r["content"]: str(r["id"]) for r in rows}
    cheese = next(v for k, v in by.items() if "cheese" in k)
    veg = next(v for k, v in by.items() if "vegetarian" in k)
    links = await _links_between(db, ow, cheese, veg)
    assert links, "cheese and vegetarian share no edge at all"
    assert all(l["reason"] for l in links), links


@pytest.mark.asyncio
async def test_burst_twenty_bounded(db, emb):
    """Stress: 20 concurrent writes — no dupes, links bounded, all storied."""
    ow = f"lkb_{uuid.uuid4().hex[:8]}"
    topics = [
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

    async def one(i):
        return await scribe.persist(
            db=db, embedder=emb, turn=_turn(topics[i], ow, i, ow),
            obs=_obs(topics[i], [f"t{i % 5}", f"u{i}"]))

    ops = await asyncio.gather(*[one(i) for i in range(20)])
    assert all(o.startswith(("NEW", "RAW")) for o in ops), ops
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s", (ow,))
    assert n == 20, f"burst lost or duped rows: {n}"
    links = await db.fetchval(
        "SELECT count(*) FROM memory_links WHERE owner = %s", (ow,))
    assert links <= 20 * (3 + 1), f"link explosion: {links}"
    bare = await db.fetchval(
        "SELECT count(*) FROM memory_links WHERE owner = %s "
        "AND (reason IS NULL OR reason = '')",
        (ow,),
    )
    assert bare == 0


@pytest.mark.asyncio
async def test_relink_repairs_old_rows(db, emb):
    from app.agents import relink as rl_agent
    from tests.test_recall import seed as _seed

    ow = f"lkr_{uuid.uuid4().hex[:8]}"
    ids = await _seed(db, emb, ow, [
        {"name": "a", "content": "The user hates cheese.",
         "tags": ["food", "cheese"], "session": ow},
        {"name": "b", "content": "The user is vegetarian.",
         "tags": ["food", "diet"], "session": ow},
    ])
    # raw SQL seeds carry no links: relink must build both kinds
    assert await db.fetchval(
        "SELECT count(*) FROM memory_links WHERE owner = %s", (ow,)) == 0
    made = await rl_agent.relink(db, ow)
    assert made["temporal"] == 1, made
    assert made["tag"] == 1, made
    links = await db.fetch(
        "SELECT relation, reason FROM memory_links WHERE owner = %s", (ow,))
    assert all(l["reason"] for l in links), links
    assert any("food" in l["reason"] for l in links if l["relation"] == "tag")
    # idempotent: second run makes nothing
    assert await rl_agent.relink(db, ow) == {"temporal": 0, "tag": 0}
    assert len(ids) == 2

"""G1: unmarked reversals must survive the familiarity gate.

Drill run 1 proved the store silently drops contradictions phrased without
explicit markers ("Groceries auto-default is killed... never automatic" died
as 'already known' 0.80, twice more for the contradiction reports). The
familiar branch now verifies: contradict -> correction lane, entail -> SKIP,
neutral -> scribe. Pinned pairs below were measured live (cosine + NLI),
not invented: contra 0.83/1.00, entail 0.98/0.99, neutral 0.91/1.00.
"""
import asyncio
import uuid

import pytest

from app import nli as nli_mod
from app.agents import cues, observer
from app.config import Settings, get_settings
from app.embeddings import Embedder

AUTH = {"Authorization": "Bearer test-token"}

BEN = "Ben does not drink alcohol."
BEN_CONTRA = "Ben drinks alcohol at parties."  # unmarked: no flip lexicon
BEN_ENTAIL = "Ben does not drink alcohol either."
BEN_NEUTRAL = "Ben does not drink alcohol on weekdays, only weekends."
G1_DESIGN = (
    "splitter.py unequal-shares design adds --shares NAME:W and NAME:W "
    "suffixes with groceries defaulting to Anna x2, weights stored per "
    "expense, and old equal-split records unchanged."
)
G1_REVERSAL = (
    "Groceries auto-default is killed: plain groceries split equally among "
    "all three; Anna-double only via explicit --shares/--split, never "
    "automatic."
)


def test_polarity_flip_markers():
    assert cues.polarity_flip(G1_REVERSAL)  # killed + never
    assert cues.polarity_flip(
        "Contradiction noticed: brain says X but code says Y.")
    assert cues.polarity_flip("Remove the groceries default.")
    assert cues.polarity_flip("We switched to Postgres.")
    # Recall-oriented by design: fires on the verb even when no stored
    # target exists ("kill the server" alone). The observer's familiar
    # branch is the gate that prevents misroutes, not this lexicon.
    assert cues.polarity_flip("kill the server")
    # Bare negations are deliberately NOT markers: restatements and
    # refinements ("either", "on weekdays") need the NLI arbiter.
    assert not cues.polarity_flip(BEN)
    assert not cues.polarity_flip(BEN_ENTAIL)
    assert not cues.polarity_flip(BEN_NEUTRAL)
    assert not cues.polarity_flip(BEN_CONTRA)
    assert not cues.polarity_flip("Add three numbers.")


def _nli_dir():
    from app import nli as n

    return n.model_dir(Settings())


@pytest.mark.asyncio
async def test_nli_verify_real_labels():
    """Real ONNX weights, real labels. Skips honestly when weights are
    absent (fresh offline clone) — never fakes the verifier."""
    if not (_nli_dir() / nli_mod.MODEL_FILE).is_file():
        pytest.skip("nli weights absent — honest skip, verifier untested")
    s = Settings()
    r = await nli_mod.verify(G1_DESIGN, G1_REVERSAL, s)
    assert r["label"] == "contradiction", r
    assert r["p_contra"] >= 0.70, r
    r = await nli_mod.verify(BEN, BEN_CONTRA, s)
    assert r["label"] == "contradiction", r
    assert r["p_contra"] >= 0.70, r
    r = await nli_mod.verify(BEN, BEN_ENTAIL, s)
    assert r["label"] == "entailment", r
    r = await nli_mod.verify(BEN, BEN_NEUTRAL, s)
    assert r["label"] == "neutral", r
    # Same-topic neutral only: far-apart pairs ("sky is blue" vs "Ben
    # drinks coffee") read contradiction 1.00 on this quant — a measured
    # quirk, unreachable in production (the gate only forwards pairs at
    # cosine >= 0.80), so the suite pins reachable behavior, not the quirk.
    r = await nli_mod.verify(
        "Ben drinks coffee.", "Ben drinks coffee in the morning.", s)
    assert r["label"] == "neutral", r


@pytest.mark.asyncio
async def test_contradiction_routes(db):
    """_contradiction routes the pinned trio through the real verifier
    against a real seeded row. Needs weights (see skip above)."""
    if not (_nli_dir() / nli_mod.MODEL_FILE).is_file():
        pytest.skip("nli weights absent — honest skip, verifier untested")
    from tests.test_recall import seed

    emb = Embedder(Settings())
    ow = f"nli_{uuid.uuid4().hex[:8]}"
    ids = await seed(db, emb, ow, [{"name": "ben", "content": BEN}])
    s = get_settings()
    route, detail, explicit = await observer._contradiction(
        db, s, ids["ben"], BEN_CONTRA)
    assert route == "contradict", detail
    assert explicit is False  # unmarked: NLI-inferred, reconcile re-verifies
    route, detail, _ = await observer._contradiction(
        db, s, ids["ben"], BEN_ENTAIL)
    assert route == "entail", detail
    route, detail, _ = await observer._contradiction(
        db, s, ids["ben"], BEN_NEUTRAL)
    assert route == "neutral", detail
    route, detail, explicit = await observer._contradiction(
        db, s, ids["ben"], G1_REVERSAL)
    assert route == "contradict", detail  # pre-filter, no model needed
    assert explicit is True  # polarity lexicon marks human intent


COFFEE = "Ben drinks coffee."
COFFEE_STOP = "Ben stopped drinking coffee."  # cos 0.851, pre-filter: stop


async def _wait_event(db, owner, turn, timeout=120):
    for _ in range(timeout):
        ev = await db.fetchrow(
            "SELECT observer_verdict, scribe_action FROM memory_events "
            "WHERE owner = %s AND turn = %s",
            (owner, turn),
        )
        if ev:
            return ev
        await asyncio.sleep(1)
    return None


async def _seed_text(db, owner, text, subject=None, predicate=None, obj=None):
    """Seed one row, then stamp the SP triple so the row matches
    production shape (LLM-scribed rows always carry SP). SP-less seeds
    take the journal path and would hide reconcile-layer bugs (seen: the
    predicate-flip SKIP only fires on SP-bearing rows)."""
    from tests.test_recall import seed

    emb = Embedder(Settings())
    ids = await seed(db, emb, owner, [{"name": "t", "content": text}])
    if subject is not None:
        await db.execute(
            'UPDATE memories SET subject = %s, predicate = %s, "object" = %s '
            "WHERE id = %s::uuid",
            (subject, predicate, obj, ids["t"]),
        )
    return ids


async def _live_blob(db, owner):
    rows = await db.fetch(
        "SELECT content FROM memories WHERE owner = %s AND valid_to IS NULL",
        (owner,),
    )
    return "\n".join(r["content"] for r in rows)


@pytest.mark.asyncio
async def test_g1_unmarked_reversal_survives_e2e(client, db):
    """Live Meta: an unmarked contradiction (0.83 familiar, NLI contra 1.00)
    lands instead of dying as 'already known'. Verdict proves the route
    (deterministic, set pre-LLM); the blob proves new truth landed
    (SUPERSEDE or journal UPDATE — the LLM picks the shape)."""
    ow = f"g1nli_{uuid.uuid4().hex[:8]}"
    await _seed_text(db, ow, BEN, "ben", "does not drink", "alcohol")
    r = await client.post("/write", json={
        "text": BEN_CONTRA, "session_id": ow, "turn": 0, "owner": ow,
        "source": {"trust": "user_direct"},
    }, headers=AUTH)
    assert r.status_code == 202
    ev = await _wait_event(db, ow, 0)
    assert ev is not None, "reversal event never logged"
    assert ev["observer_verdict"]["keep"] is True
    assert "contra" in ev["observer_verdict"]["reason"], ev["observer_verdict"]
    assert ev["scribe_action"]["op"] == "SUPERSEDE", ev["scribe_action"]
    blob = await _live_blob(db, ow)
    assert "parties" in blob, f"new truth not in live rows: {blob!r}"


@pytest.mark.asyncio
async def test_g1_marked_reversal_survives_e2e(client, db):
    """Live Meta: same, via the pre-filter path ('stopped', 0.851). Two
    code paths into the correction lane, both proven end to end."""
    ow = f"g1pre_{uuid.uuid4().hex[:8]}"
    await _seed_text(db, ow, COFFEE, "ben", "drinks", "coffee")
    r = await client.post("/write", json={
        "text": COFFEE_STOP, "session_id": ow, "turn": 0, "owner": ow,
        "source": {"trust": "user_direct"},
    }, headers=AUTH)
    assert r.status_code == 202
    ev = await _wait_event(db, ow, 0)
    assert ev is not None, "reversal event never logged"
    assert ev["observer_verdict"]["keep"] is True
    assert "contra" in ev["observer_verdict"]["reason"], ev["observer_verdict"]
    assert ev["scribe_action"]["op"] == "SUPERSEDE", ev["scribe_action"]
    blob = await _live_blob(db, ow)
    assert blob != COFFEE, "reversal kept but nothing new landed"


@pytest.mark.asyncio
async def test_g1_reversal_dies_flag_off(client, booted_app, db):
    """Sensitivity proof: the same reversal with the verifier disabled dies
    the old way. If this ever fails, the e2e above proves nothing."""
    booted_app.state.settings.nli_enabled = False
    ow = f"g1off_{uuid.uuid4().hex[:8]}"
    await _seed_text(db, ow, BEN, "ben", "does not drink", "alcohol")
    r = await client.post("/write", json={
        "text": BEN_CONTRA, "session_id": ow, "turn": 0, "owner": ow,
        "source": {"trust": "user_direct"},
    }, headers=AUTH)
    assert r.status_code == 202
    ev = await _wait_event(db, ow, 0, timeout=60)
    assert ev is not None, "reversal event never logged"
    assert ev["observer_verdict"]["keep"] is False
    assert "already known" in ev["observer_verdict"]["reason"]


@pytest.mark.asyncio
async def test_dup_restatement_skips_e2e(client, db):
    """Live app, no LLM needed: a true restatement (0.98, NLI entail) still
    SKIPs at the observer and leaves exactly one live row — the gate keeps
    its dedup contract after the rewire."""
    ow = f"dup_{uuid.uuid4().hex[:8]}"
    await _seed_text(db, ow, BEN, "ben", "does not drink", "alcohol")
    r = await client.post("/write", json={
        "text": BEN_ENTAIL, "session_id": ow, "turn": 0, "owner": ow,
        "source": {"trust": "user_direct"},
    }, headers=AUTH)
    assert r.status_code == 202
    ev = await _wait_event(db, ow, 0, timeout=60)
    assert ev is not None, "restatement event never logged"
    assert "already known" in ev["observer_verdict"]["reason"]
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = %s AND valid_to IS NULL",
        (ow,),
    )
    assert n == 1, f"restatement duplicated the row (n={n})"

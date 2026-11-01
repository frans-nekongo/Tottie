"""Updater: dup merge + contradiction sweep, newest-wins. Real DB, real
embeds, real local NLI — deterministic, no LLM calls.
"""
import uuid

import pytest
from psycopg.types.json import Json

from app.agents import updater
from app.config import Settings, get_settings
from app.db import pgvector_literal
from app.embeddings import Embedder
from tests.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}

BEN = "Ben does not drink alcohol."
BEN_CONTRA = "Ben drinks alcohol at parties."


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


async def _seed(db, emb, owner, content, hours_ago=0, subject=None,
              predicate=None, obj=None):
    vec, _ = await emb.embed(content)
    row = await db.execute_returning(
        "INSERT INTO memories (owner, tier, kind, subject, predicate, "
        '"object", content, trust, source, '
        "embedding, embedding_model, hash, created_at) VALUES "
        "(%s,'knowledge','fact',%s,%s,%s,%s,'user_direct',%s,%s::vector,%s,%s,"
        "now() - make_interval(hours => %s)) RETURNING id",
        (owner, subject, predicate, obj, content,
         Json({"session": "seed", "turn": 0}),
         pgvector_literal(vec), emb.model_name, uuid.uuid4().hex, hours_ago),
    )
    return str(row["id"])


@pytest.mark.asyncio
async def test_merge_exact_dup(db, emb):
    old = await _seed(db, emb, "up1", "The vault code is 1234.", hours_ago=2)
    new = await _seed(db, emb, "up1", "The vault code is 1234.")
    out = await updater.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="up1")
    assert out["merged"] == 1, out
    live = await db.fetch(
        "SELECT id FROM memories WHERE owner = 'up1' AND valid_to IS NULL")
    assert [str(r["id"]) for r in live] == [new]
    link = await db.fetchrow(
        "SELECT relation FROM memory_links WHERE src = %s::uuid "
        "AND dst = %s::uuid", (new, old))
    assert link["relation"] == "duplicate"


@pytest.mark.asyncio
async def test_contra_newest_wins(db, emb):
    import math

    def _cos(a, b):
        return sum(x * y for x, y in zip(a, b)) / (
            math.sqrt(sum(x * x for x in a))
            * math.sqrt(sum(y * y for y in b)))
    avec, _ = await emb.embed(BEN)
    bvec, _ = await emb.embed(BEN_CONTRA)
    cos = _cos(avec, bvec)
    # Between the floors: neighbor-gated into the contra pass, below dup.
    assert updater.CONTRA_NEIGHBOR <= cos < updater.DUP_COSINE, cos
    await _seed(db, emb, "up2", BEN, hours_ago=2)
    await _seed(db, emb, "up2", BEN_CONTRA)
    out = await updater.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="up2")
    assert out["retired_contra"] == 1, out
    live = await db.fetch(
        "SELECT content FROM memories WHERE owner = 'up2' "
        "AND valid_to IS NULL")
    assert [r["content"] for r in live] == [BEN_CONTRA]


@pytest.mark.asyncio
async def test_parallel_specs_not_dups(db, emb):
    # Live kill at 0.966: 12Hz vs 25Hz tokenizers are DIFFERENT specs
    # in parallel phrasing. The 0.98 bar spares them.
    a = ("Qwen-TTS-Tokenizer-25Hz is a 25 Hz single-codebook tokenizer "
         "built upon Qwen2-Audio via two-stage training with ASR "
         "pretraining plus VQ layer then mel-spectrogram decoder "
         "fine-tuning.")
    b = ("Qwen-TTS-Tokenizer-12Hz is a 12.5 Hz multi-codebook tokenizer "
         "decomposing speech into semantic codebook and acoustic "
         "codebook with 15-layer RVQ, guided by WavLM teacher.")
    # Realistic variant-name subjects (prod scribe names the variant):
    # the differing numbers live in the subjects, so the numeric rule
    # reads complement, never conflict. (With NULL subjects a
    # high-masked pair is indistinguishable from true conflict and
    # SHOULD retire — e.g. "fee is 450" vs "fee is 500".)
    await _seed(db, emb, "up5", a, hours_ago=2,
                subject="Qwen-TTS-Tokenizer-25Hz", predicate="is",
                obj="single-codebook tokenizer")
    await _seed(db, emb, "up5", b, subject="Qwen-TTS-Tokenizer-12Hz",
                predicate="is", obj="multi-codebook tokenizer")
    out = await updater.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="up5")
    assert out["merged"] == 0, out
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = 'up5' "
        "AND valid_to IS NULL")
    assert n == 2


@pytest.mark.asyncio
async def test_facet_pair_survives_contra(db, emb):
    # Live kills: same-subject different-facets (G4 vs G7, fetch vs
    # retire) misfire symmetric-contra ~1.00. No polarity flip and
    # < 4 shared words = no opposition.
    a = "curator.py run_sweep retires memory by setting valid_to."
    b = "curator.py run_sweep fetches active memories ordered by date."
    await _seed(db, emb, "up6", a, hours_ago=2)
    await _seed(db, emb, "up6", b)
    out = await updater.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="up6")
    assert out["retired_contra"] == 0, out
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = 'up6' "
        "AND valid_to IS NULL")
    assert n == 2


@pytest.mark.asyncio
async def test_speech_act_pair_survives(db, emb):
    """Request vs fulfillment reads symmetric-contra (1.00/0.99 live)
    but a speech act is immutable history: both rows must survive."""
    req = ("Owner requested a CLI habit tracker for reading, running, and "
           "meditating with logging and streaks in /tmp/habits.")
    built = ("Owner built stdlib-only habit tracker at "
             "/tmp/habits/habits.py with log and streaks commands storing "
             "habit to sorted ISO date list.")
    await _seed(db, emb, "up4", req, hours_ago=2)
    await _seed(db, emb, "up4", built)
    out = await updater.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="up4")
    assert out["retired_contra"] == 0, out
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = 'up4' "
        "AND valid_to IS NULL")
    assert n == 2


@pytest.mark.asyncio
async def test_numeric_conflict_retires_older(db, emb):
    # Live pair, exact prod contents: NLI reads swapped years as
    # neutral, so both rows coexisted and recall served "2025 vs 2026"
    # with no flag. Same claim shape (masked 0.9013) + swapped values
    # + number-free subjects = conflict, newest wins.
    old = ("NUST Postgraduate Application has deadline 26 September "
           "2025 and application fee N$360.")
    new = ("NUST postgraduate application closing date is 26 September "
           "2026.")
    await _seed(db, emb, "up7", old, hours_ago=2,
                subject="Postgraduate Application Form",
                predicate="requires", obj="N$360 fee")
    await _seed(db, emb, "up7", new,
                subject="NUST", predicate="closes",
                obj="postgraduate applications")
    out = await updater.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="up7")
    assert out["retired_contra"] == 1, out
    assert out["items"][0].get("via") == "numeric", out
    live = await db.fetch(
        "SELECT content FROM memories WHERE owner = 'up7' "
        "AND valid_to IS NULL")
    assert [r["content"] for r in live] == [new]


@pytest.mark.asyncio
async def test_numeric_conflict_beyond_row_window(db, emb):
    # Pass 3: pass 2 only sweeps recent rows (row_cap). Old numeric
    # conflicts (prod deadline pair sat at rank ~672) must still
    # resolve. row_cap=0 disables pass 2 entirely: pass 3 alone fires.
    old = ("NUST Postgraduate Application has deadline 26 September "
           "2025 and application fee N$360.")
    new = ("NUST postgraduate application closing date is 26 September "
           "2026.")
    await _seed(db, emb, "up9", old, hours_ago=2,
                subject="Postgraduate Application Form",
                predicate="requires", obj="N$360 fee")
    await _seed(db, emb, "up9", new,
                subject="NUST", predicate="closes",
                obj="postgraduate applications")
    out = await updater.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="up9",
        row_cap=0)
    assert out["retired_contra"] == 1, out
    assert out["items"][0].get("via") == "numeric", out


@pytest.mark.asyncio
async def test_boilerplate_pair_survives_contra(db, emb):
    # Live kill at NLI 0.99: shared template words (POST, /agents,
    # Tottie) are not aboutness. Two endpoints, both true, both live.
    pair = ("POST /agents/pair in Tottie sets connected=true for "
            "matching id and owner, returning 404 unknown agent if no "
            "row.")
    beat = ("POST /agents/heartbeat in Tottie upserts agent (id, owner, "
            "label) and updates last_seen, returning connected status.")
    await _seed(db, emb, "up8", beat, hours_ago=2)
    await _seed(db, emb, "up8", pair)
    out = await updater.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="up8")
    assert out["retired_contra"] == 0, out
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = 'up8' "
        "AND valid_to IS NULL")
    assert n == 2


@pytest.mark.asyncio
async def test_spec_sheets_not_numeric_conflict(db, emb):
    # Live false kill at masked 0.908: same-variant spec sheets share
    # shape but differ in 5 numbers (different measurements = different
    # facts), not one swapped slot (deadline: 3). Symdiff cap silences.
    a = ("Qwen-TTS-Tokenizer-12Hz uses pure left-context streaming "
         "codec decoder at 12.5Hz where 1 token equals 80ms, grouped "
         "as 4 tokens per 320ms speech packet to reduce scheduling "
         "overhead.")
    b = ("Qwen-TTS-Tokenizer-12Hz is a 12.5 Hz multi-codebook "
         "tokenizer decomposing speech into semantic codebook and "
         "acoustic codebook with 15-layer RVQ, guided by WavLM "
         "teacher.")
    await _seed(db, emb, "up10", b, hours_ago=2,
                subject="Qwen-TTS-Tokenizer-12Hz", predicate="is",
                obj="multi-codebook tokenizer")
    await _seed(db, emb, "up10", a,
                subject="Qwen-TTS-Tokenizer-12Hz", predicate="uses",
                obj="streaming codec decoder")
    out = await updater.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="up10")
    assert out["retired_contra"] == 0, out
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = 'up10' "
        "AND valid_to IS NULL")
    assert n == 2


@pytest.mark.asyncio
async def test_incidental_numbers_not_conflict(db, emb):
    # Live false kills at masked 0.905-0.913: same-template test
    # descriptions with incidental weights (1.0 vs 0.7/0.3). Masking
    # barely moves similarity (+0.012/-0.007: the test name differs,
    # weights don't matter), so the delta rule silences them. A real
    # swap (deadline year) gains +0.020.
    a = ("test_linker.py expects far-apart same-subject pair to link "
         "as plain entity edge with weight 0.7, not contradicts.")
    b = ("test_linker.py expects entailment pair to link as supports "
         "edge with weight 1.0.")
    await _seed(db, emb, "up11", b, hours_ago=2,
                subject="test_linker", predicate="expects",
                obj="supports")
    await _seed(db, emb, "up11", a,
                subject="test_linker", predicate="expects",
                obj="entity")
    out = await updater.run_sweep(
        db=db, embedder=emb, settings=get_settings(), owner="up11")
    assert out["retired_contra"] == 0, out
    n = await db.fetchval(
        "SELECT count(*) FROM memories WHERE owner = 'up11' "
        "AND valid_to IS NULL")
    assert n == 2


@pytest.mark.asyncio
async def test_sweep_route_queues_and_ledgers(client, db, emb):
    await _seed(db, emb, "up3", "The vault code is 9999.", hours_ago=2)
    await _seed(db, emb, "up3", "The vault code is 9999.")
    r = await client.post("/sweep", json={"owner": "up3"}, headers=AUTH)
    assert r.status_code == 202
    assert r.json()["mode"] == "queued"
    ev = None
    for _ in range(60):
        import asyncio
        await asyncio.sleep(1)
        ev = await db.fetchrow(
            "SELECT scribe_action FROM memory_events WHERE owner = 'up3' "
            "AND session_id = 'sweep'")
        if ev:
            break
    assert ev and ev["scribe_action"]["op"] == "UPDATE_SWEEP", ev
    assert ev["scribe_action"]["merged"] == 1, ev["scribe_action"]

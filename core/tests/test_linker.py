"""Linker: shared-entity edges + NLI typing. Real DB, real local NLI,
no LLM calls. NLI directions reuse the pinned BEN suite.
"""
import itertools
import uuid

import pytest
from psycopg.types.json import Json

from app.agents import linker
from app.config import Settings, get_settings
from app.db import pgvector_literal
from app.embeddings import Embedder

BEN = "Ben does not drink alcohol."
BEN_ENTAIL = "Ben does not drink alcohol either."
BEN_CONTRA = "Ben drinks alcohol at parties."
BEN_NEUTRAL = "Ben does not drink alcohol on weekdays, only weekends."


@pytest.fixture(scope="module")
def emb():
    return Embedder(Settings())


_PRED = itertools.count()


async def _seed(db, emb, owner, content, subject, obj="x"):
    predicate = f"p{next(_PRED)}"
    vec, _ = await emb.embed(content)
    row = await db.execute_returning(
        'INSERT INTO memories (owner, tier, kind, subject, predicate, '
        '"object", content, trust, source, embedding, embedding_model, '
        "hash) VALUES (%s,'knowledge','fact',%s,%s,%s,%s,'user_direct',"
        "%s,%s::vector,%s,%s) RETURNING id",
        (owner, subject, predicate, obj, content,
         Json({"session": "seed", "turn": 0}), pgvector_literal(vec),
         emb.model_name, uuid.uuid4().hex),
    )
    return str(row["id"])


async def _edge(db, src, dst):
    return await db.fetchrow(
        "SELECT relation, weight FROM memory_links WHERE src = %s::uuid "
        "AND dst = %s::uuid AND relation IN "
        "('entity', 'supports', 'contradicts')",
        (src, dst),
    )


@pytest.mark.asyncio
async def test_shared_subject_links_plain_entity(db, emb):
    """Far-apart pairs read contra ~1.00 (int8 quirk); below 0.80 they
    stay plain entity edges instead of quirk-typed contradicts."""
    chess = "Ben plays chess on Sundays."
    a = await _seed(db, emb, "lk1", BEN, "Ben")
    b = await _seed(db, emb, "lk1", chess, "Ben")
    out = await linker.link_row(
        db=db, embedder=emb, settings=get_settings(), memory_id=a)
    assert out["linked"] == 1, out
    e = await _edge(db, a, b)
    assert e["relation"] == "entity" and e["weight"] == 0.7, e


@pytest.mark.asyncio
async def test_reverse_entail_links_supports(db, emb):
    a = await _seed(db, emb, "lk5", BEN, "Ben")
    b = await _seed(db, emb, "lk5", BEN_NEUTRAL, "Ben")
    out = await linker.link_row(
        db=db, embedder=emb, settings=get_settings(), memory_id=a)
    e = await _edge(db, a, b)
    assert e["relation"] == "supports", (out, e)


@pytest.mark.asyncio
async def test_entailment_links_supports(db, emb):
    a = await _seed(db, emb, "lk2", BEN, "Ben")
    b = await _seed(db, emb, "lk2", BEN_ENTAIL, "Ben")
    out = await linker.link_row(
        db=db, embedder=emb, settings=get_settings(), memory_id=a)
    e = await _edge(db, a, b)
    assert e["relation"] == "supports" and e["weight"] == 1.0, out


@pytest.mark.asyncio
async def test_symmetric_contra_links_contradicts(db, emb):
    a = await _seed(db, emb, "lk3", BEN, "Ben")
    b = await _seed(db, emb, "lk3", BEN_CONTRA, "Ben")
    out = await linker.link_row(
        db=db, embedder=emb, settings=get_settings(), memory_id=a)
    e = await _edge(db, a, b)
    assert e["relation"] == "contradicts" and e["weight"] == 0.3, out


@pytest.mark.asyncio
async def test_same_subject_facets_stay_entity(db, emb):
    # Live misfire: "X does A" vs "X does B" (different facets of one
    # file) read symmetric-contra 0.97-1.00 and typed 14 false
    # contradicts. Polarity-only gate: no flip, no numbers = entity.
    a = await _seed(db, emb, "lk6",
                    "curator.py run_sweep retires memory by setting valid_to.",
                    "curator")
    b = await _seed(db, emb, "lk6",
                    "curator.py run_sweep fetches active memories ordered by date.",
                    "curator")
    out = await linker.link_row(
        db=db, embedder=emb, settings=get_settings(), memory_id=a)
    e = await _edge(db, a, b)
    assert e["relation"] == "entity", (out, e)


@pytest.mark.asyncio
async def test_parallel_specs_stay_entity(db, emb):
    # Near-identical phrasing (cos 0.966 here) with differing specs
    # is complement, not clash — symmetric-contra fires 1.00/1.00 and
    # still must not type contradicts (polarity-only shared rule).
    a = ("Qwen-TTS-Tokenizer-25Hz is a 25 Hz single-codebook tokenizer "
         "built upon Qwen2-Audio.")
    b = ("Qwen-TTS-Tokenizer-12Hz is a 12.5 Hz multi-codebook tokenizer "
         "decomposing speech into codebooks.")
    ida = await _seed(db, emb, "lk7", a, "qwen")
    idb = await _seed(db, emb, "lk7", b, "qwen")
    out = await linker.link_row(
        db=db, embedder=emb, settings=get_settings(), memory_id=ida)
    e = await _edge(db, ida, idb)
    assert e["relation"] == "entity", (out, e)


@pytest.mark.asyncio
async def test_polarity_needs_same_object():
    """v3: a polarity flip convicts only about one slot. NLI is stubbed
    symmetric-contra so the test pins the object rule, not the model."""
    class StubNLI:
        async def verify(self, a, b, settings):
            return {"label": "contradiction", "p_contra": 0.99,
                    "p_entail": 0.0}

    settings = get_settings()
    # Same object: a flip about one slot is a reversal.
    rel, _, _ = await linker._type_pair(
        StubNLI(), settings, "Ben never drinks.", "Ben drinks.", 0.85,
        "alcohol", "alcohol")
    assert rel == "contradicts", rel
    # Differing objects: a "never" in one test description vs another
    # test's expectation is noise about different slots (live kill:
    # test_linker never-links retired reverse-entailment).
    rel, _, _ = await linker._type_pair(
        StubNLI(), settings,
        "test_linker expects owner rows to never link.",
        "test_linker expects reverse pair to link as supports.", 0.85,
        "never-link", "supports")
    assert rel == "entity", rel
    # NULL objects can't differ: polarity alone decides.
    rel, _, _ = await linker._type_pair(
        StubNLI(), settings, "Ben never drinks.", "Ben drinks.", 0.85,
        None, None)
    assert rel == "contradicts", rel


def test_same_object_tolerates_paraphrase():
    """F2b: '4000 chars' vs 'output at 4000 chars' is one slot — exact
    equality vetoed a 0.998/0.986 symmetric-contra pair live (the
    truncation twin the sweep could not kill). Real subjects/objects
    from the production rows."""
    assert linker.is_opposition(
        "mcp_client truncates output at 4000 chars.",
        "mcp_client no longer truncates output at 4000 chars.", 0.91,
        "4000 chars", "output at 4000 chars",
        "mcp_client", "mcp_client") is True


def test_same_subject_bridges_file_extension_variants():
    """Sibling scribes wrote 'mcp_client' and 'mcp_client.py' for one
    entity; the stale truncation row must still die. 'py' is stripped
    so it can never bridge two DIFFERENT files."""
    assert linker.is_opposition(
        "mcp_client.py prints tool output as pretty JSON truncated to 4000 chars.",
        "mcp_client no longer truncates output at 4000 chars.", 0.85,
        "output to 4000 chars", "output at 4000 chars",
        "mcp_client.py", "mcp_client") is True


def test_same_object_ignores_stopword_overlap():
    """'the code' vs 'the gate' share only 'the' — different slots,
    still vetoed."""
    assert linker.is_opposition(
        "The vault code is set.", "The garden gate is not set.", 0.85,
        "the code", "the gate") is False


def test_same_subject_vetoes_feature_vs_test_facets():
    """Live murder, real production values: objects NEST ('concept
    boost' in 'concept boost leg') so the overlap rule fires — only
    the disjoint subjects (retrieve.py vs the test name) silence the
    gate. A feature fact must never die for its own test."""
    assert linker.is_opposition(
        "retrieve.py adds an optional concept-boost leg when recall_concepts is enabled.",
        "test_concept_boost_promotes_only_matches verifies concept leg is boost-only, no LLM.",
        0.85, "concept boost leg", "concept boost",
        "retrieve.py", "test_concept_boost_promotes_only_matches") is False


@pytest.mark.asyncio
async def test_owner_subject_never_links(db, emb):
    a = await _seed(db, emb, "lk4", "Owner fixed the bug.", "owner",
                    obj="bug")
    b = await _seed(db, emb, "lk4", "Owner wrote a test.", "owner",
                    obj="test")
    out = await linker.link_row(
        db=db, embedder=emb, settings=get_settings(), memory_id=a)
    assert out == {"linked": 0, "typed": {}}, out
    assert await _edge(db, a, b) is None

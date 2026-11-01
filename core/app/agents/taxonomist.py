"""The Taxonomist: discovered topics. No fixed map: topics emerge
bottom-up from embedding similarity, so habits rows, splitter rows,
and Lean rows group themselves out of the owner's data.

Method (deterministic, no LLM, no NLI): topics are connected
components of the TOPIC_COSINE pair graph (tight embedding pairs).
Singletons keep their own topic (every live row ends tagged). Names
are top member terms (stop-filtered); LLM naming is deferred — names
are labels, never structure.

Areas (the level above topics: school/company) are DELIBERATELY CUT
from v1. Three discriminants were tried on the live 210-row store
and all failed honestly:
  1. cosine union-find: 0.60 chains everything into one mega-area,
     0.65+ shatters into singletons — no valley in between;
  2. centroid coherence: every term scores 0.75-0.83, including
     "being"/"after" (MiniLM anisotropy — random rows already sit
     in a narrow cone);
  3. co-term entropy ratio: "test" looks focused (0.87, terse
     report rows) while "lean" looks random (1.01, diverse rows) —
     it measures terseness, not topicality.
The store is one single-project blob; no unsupervised signal can
manufacture life buckets that are not in the data. Revisit when the
store spans distinct life areas (measurable trigger: drill seeds
with school + company + health rows that topics alone cannot
separate for navigation). Until then, topics ARE the taxonomy.

Writes `topic:<slug>` tags (old topic:/area: tags are replaced,
making sweeps idempotent — stale area: tags from earlier sweeps are
scrubbed). The tag-assoc retrieval leg and the UI group on these
tags for free.
"""
import logging
import re
from collections import Counter

from psycopg.types.json import Json

log = logging.getLogger("tottie.taxonomist")

TOPIC_COSINE = 0.75
PAIR_CAP = 5000
ROW_CAP = 500

STOPS = frozenset(
    "the and for with from that this these those then than them they you "
    "your our have has had can could should would will what when where "
    "which who whom whose why how does did done are was were owner user "
    "system memory memories row rows new just now today".split()
)


def _terms(text):
    return [w for w in re.findall(r"[a-z]+", (text or "").lower())
            if len(w) > 3 and w not in STOPS]


def _name(members_contents, taken, fallback):
    counts: Counter[str] = Counter()
    for c in members_contents:
        counts.update(_terms(c))
    for term, _ in counts.most_common():
        slug = re.sub(r"[^a-z0-9]+", "-", term).strip("-")
        if slug and slug not in taken:
            taken.add(slug)
            return slug
    taken.add(fallback)
    return fallback


def _components(ids, edges):
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups: dict[str, list[str]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


async def run_sweep(*, db, embedder, settings, owner: str) -> dict:
    rows = await db.fetch(
        "SELECT id, content, tags FROM memories WHERE owner = %s "
        "AND valid_to IS NULL AND embedding IS NOT NULL "
        "ORDER BY created_at DESC LIMIT %s",
        (owner, ROW_CAP),
    )
    by_id = {str(r["id"]): r for r in rows}
    ids = list(by_id)
    pairs = await db.fetch(
        "SELECT a.id AS a, b.id AS b, "
        "1 - (a.embedding <=> b.embedding) AS cos "
        "FROM memories a JOIN memories b "
        "ON a.owner = b.owner AND a.id < b.id "
        "WHERE a.owner = %s AND a.valid_to IS NULL AND b.valid_to IS NULL "
        "AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL "
        "AND 1 - (a.embedding <=> b.embedding) >= %s "
        "ORDER BY cos DESC LIMIT %s",
        (owner, TOPIC_COSINE, PAIR_CAP),
    )
    topic_edges = [(str(p["a"]), str(p["b"])) for p in pairs
                   if p["cos"] >= TOPIC_COSINE]
    topics = _components(ids, topic_edges)
    taken: set[str] = set()
    tagged = 0
    for members in topics:
        contents = [by_id[i]["content"] or "" for i in members]
        topic = _name(contents, taken, f"topic-{len(taken)}")
        for i in members:
            tags = [t for t in (by_id[i]["tags"] or [])
                    if not t.startswith("topic:") and not t.startswith("area:")]
            tags += [f"topic:{topic}"]
            await db.execute(
                "UPDATE memories SET tags = %s WHERE id = %s::uuid",
                (tags, i),
            )
            tagged += 1
    summary = {"topics": len(topics), "tagged": tagged, "rows": len(rows)}
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance, "
        "observer_verdict, scribe_action) VALUES (%s,'sweep',NULL,%s,%s,%s)",
        (owner, f"taxonomy sweep: {len(topics)} topics, "
                f"{tagged} rows tagged",
         Json({"keep": True, "reason": "taxonomy sweep"}),
         Json({"op": "TAXONOMY_SWEEP", **summary})),
    )
    log.info("taxonomist swept %s: %s", owner, summary)
    return summary


async def handle_job(*, db, embedder, settings, job) -> dict:
    """Queue adapter: TAXONOMY_SWEEP jobs carry {owner} in the payload."""
    return await run_sweep(
        db=db, embedder=embedder, settings=settings,
        owner=job.payload.get("owner", settings.owner),
    )

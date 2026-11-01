"""The Taxonomist: discovered hierarchy. No fixed map: topics and areas
emerge bottom-up from embedding similarity, so school/masters and
company/business-docs shape themselves out of the owner's data.

Method (deterministic, no LLM, no NLI): topics are connected
components of the TOPIC_COSINE pair graph (tight embedding pairs).
Areas are connected components over SHARED DISTINCTIVE TERMS —
embedding cosine cannot see areas (0.60 chains the whole store into
one mega-area via background dev vocabulary; 0.65+ shatters into
singletons), but rare shared words ("splitter", "habits.py", "lean")
carve life buckets cleanly. Singletons keep their own topic and area
(every live row ends tagged). Names are top terms of member contents
(stop-filtered); LLM naming is deferred — names are labels, never
structure.

Writes `topic:<slug>` + `area:<slug>` tags (old topic:/area: tags are
replaced, making sweeps idempotent). The tag-assoc retrieval leg and
the UI group on these tags for free.
"""
import logging
import re
from collections import Counter

from psycopg.types.json import Json

log = logging.getLogger("tottie.taxonomist")

TOPIC_COSINE = 0.75
PAIR_CAP = 5000
ROW_CAP = 500
# Distinctive = appears in 2..8 rows: shared enough to join, rare
# enough to mean something. "test"/"verify" (df 50+) never area.
AREA_DF_MIN = 2
AREA_DF_MAX = 8

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


def _area_groups(by_id):
    """Areas = components over shared distinctive terms."""
    terms: dict[str, set[str]] = {}
    for i, r in by_id.items():
        for t in set(_terms(r["content"] or "")):
            terms.setdefault(t, set()).add(i)
    edges = []
    for holders in terms.values():
        if AREA_DF_MIN <= len(holders) <= AREA_DF_MAX:
            holders = sorted(holders)
            edges += [(holders[k], holders[k + 1])
                      for k in range(len(holders) - 1)]
    return _components(list(by_id), edges)


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
    areas = _area_groups(by_id)
    taken: set[str] = set()
    area_name: dict[str, str] = {}
    for members in areas:
        contents = [by_id[i]["content"] or "" for i in members]
        name = _name(contents, taken, f"area-{len(taken)}")
        for i in members:
            area_name[i] = name
    tagged = 0
    for members in topics:
        contents = [by_id[i]["content"] or "" for i in members]
        topic = _name(contents, taken, f"topic-{len(taken)}")
        for i in members:
            tags = [t for t in (by_id[i]["tags"] or [])
                    if not t.startswith("topic:") and not t.startswith("area:")]
            tags += [f"topic:{topic}", f"area:{area_name[i]}"]
            await db.execute(
                "UPDATE memories SET tags = %s WHERE id = %s::uuid",
                (tags, i),
            )
            tagged += 1
    summary = {"topics": len(topics), "areas": len(areas),
               "tagged": tagged, "rows": len(rows)}
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance, "
        "observer_verdict, scribe_action) VALUES (%s,'sweep',NULL,%s,%s,%s)",
        (owner, f"taxonomy sweep: {len(topics)} topics, {len(areas)} areas, "
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

"""The Taxonomist: discovered topics + provenance areas. No fixed map:
topics emerge bottom-up from embedding similarity; areas emerge from
WHERE the agent read (repo root of the file, else topic majority).

Method (deterministic, no LLM, no NLI): topics are connected
components of the TOPIC_COSINE pair graph (tight embedding pairs).
Singletons keep their own topic (every live row ends tagged). Names
are top member terms (stop-filtered); LLM naming is deferred — names
are labels, never structure.

Areas are PROVENANCE, not cosine — and that order matters. Four
content-based discriminants failed honestly (cosine union-find
chains school+company into one mega-area even at 0.70 through
shared AI vocabulary; centroid coherence; co-term entropy; anchor
terms): school and company TALK alike, so no content signal splits
them. But every memory knows where it was read: rows from the
school folder ARE school, rows from the company repo ARE company.
Area = nearest ancestor dir containing .git, else the file's parent
dir (repo roots unite subdirs: specs/ + technical/ are one repo).
Turn rows (replies, no file) inherit their topic's plurality area;
topics with no file rows are the live session. No hand lists: any
folder read in future becomes its own area the same way.

Writes `topic:<slug>` + `area:<slug>` tags (old ones replaced,
sweeps idempotent). The tag-assoc retrieval leg and the UI group on
these tags for free.
"""
import logging
import os
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


def _area_root(path: str, cache: dict) -> str:
    """Area root: nearest ancestor containing .git, else parent dir.
    Returns the slug. Walk-up is cached per sweep."""
    if path in cache:
        return cache[path]
    d = os.path.dirname(path) or "/"
    root = None
    for _ in range(12):
        if os.path.isdir(os.path.join(d, ".git")):
            root = d
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    if root is None:
        root = os.path.dirname(path) or "/"
    slug = re.sub(r"[^a-z0-9]+", "-", os.path.basename(root).lower()
                  ).strip("-")
    # Our own PDF-extraction scratch dir, not user content: name the
    # subject, not the artifact.
    if slug.endswith("-txt"):
        slug = slug[:-4]
    # Session-id-shaped dirs (agent transcripts, sandboxes) are not
    # areas: a UUID slug means no provenance, so fall back to the topic
    # vote / session instead of minting area:<uuid> (16 rows, live).
    if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
                    r"[0-9a-f]{12}", slug or ""):
        cache[path] = None
        return None
    cache[path] = slug or "files"
    return cache[path]


def _read_path(utterance: str | None) -> str | None:
    m = re.match(r"\[file read: (.+?) — part \d+/\d+\]", utterance or "")
    return m.group(1) if m else None


async def run_sweep(*, db, embedder, settings, owner: str) -> dict:
    rows = await db.fetch(
        "SELECT id, content, tags, source FROM memories WHERE owner = %s "
        "AND valid_to IS NULL AND embedding IS NOT NULL "
        # Repair-first: rows missing an area tag (or carrying a malformed
        # UUID one) jump the recency queue, or revivals and old rows
        # outside the window keep stale tags forever (live: 2 UUID rows
        # fell out of the window after 68 revivals).
        "ORDER BY (tags::text LIKE '%%area:%%' "
        "AND tags::text !~ 'area:[0-9a-f]{8}-') ASC, "
        "created_at DESC LIMIT %s",
        (owner, ROW_CAP),
    )
    by_id = {str(r["id"]): r for r in rows}
    ids = list(by_id)
    evs = await db.fetch(
        "SELECT session_id, turn, utterance FROM memory_events "
        "WHERE owner = %s",
        (owner,),
    )
    utt = {(e["session_id"], e["turn"]): e["utterance"] for e in evs}
    cache: dict[str, str] = {}
    row_area: dict[str, str | None] = {}
    for i in ids:
        src = by_id[i].get("source") or {}
        turns = src.get("turns") or ([src["turn"]] if src.get("turn")
                                     is not None else [])
        area = None
        for t in turns:
            path = _read_path(utt.get((src.get("session"), t)))
            if path:
                area = _area_root(path, cache) or area
                if area:
                    break
        row_area[i] = area
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
    # Pairs span all valid rows but ids is the latest ROW_CAP window:
    # drop edges touching rows outside the window (else KeyError once
    # the owner passes ROW_CAP rows).
    in_window = set(ids)
    topic_edges = [(str(p["a"]), str(p["b"])) for p in pairs
                   if p["cos"] >= TOPIC_COSINE
                   and str(p["a"]) in in_window
                   and str(p["b"]) in in_window]
    topics = _components(ids, topic_edges)
    taken: set[str] = set()
    tagged = 0
    areas: set[str] = set()
    for members in topics:
        contents = [by_id[i]["content"] or "" for i in members]
        topic = _name(contents, taken, f"topic-{len(taken)}")
        votes = Counter(row_area[i] for i in members
                        if row_area[i] is not None)
        fallback = votes.most_common(1)[0][0] if votes else "session"
        for i in members:
            # Own provenance wins: a company row in a school-majority
            # topic stays company (live case: 2 RAG rows). The topic
            # vote exists for turn rows, which have no file to read.
            area = row_area[i] or fallback
            areas.add(area)
            tags = [t for t in (by_id[i]["tags"] or [])
                    if not t.startswith("topic:") and not t.startswith("area:")]
            tags += [f"topic:{topic}", f"area:{area}"]
            await db.execute(
                "UPDATE memories SET tags = %s WHERE id = %s::uuid",
                (tags, i),
            )
            tagged += 1
    summary = {"topics": len(topics), "areas": sorted(areas),
               "tagged": tagged, "rows": len(rows)}
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance, "
        "observer_verdict, scribe_action) VALUES (%s,'sweep',NULL,%s,%s,%s)",
        (owner, f"taxonomy sweep: {len(topics)} topics, "
                f"{len(areas)} areas, {tagged} rows tagged",
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

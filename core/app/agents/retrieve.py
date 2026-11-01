"""Associative recall: three legs, RRF fusion, spreading activation, card.

Ranked branch: identity slice (pinned on the human path; briefs gate it
to identity-framed stimuli) + vector/lexical/associative legs
in ONE statement + RRF(k=60) + 2-hop BFS over memory_links + confidence with
honest abstain + 400-token Context Card + retrieval story path.
Replay branch (recency cues): ordered session events, no similarity search.
REFERENCE cues resolve their referent first (recent session episodes by
entity/definite-noun/word overlap, recency+salience tie-break, the picked
turn named in the story) and recall against the expanded query; plural
referents ("they", "those DBs", "them") resolve to ALL matching recent
candidates. An unresolvable referent abstains honestly instead of falling
through to general recall.
Every recall fires due intentions inline, bumps access_counts (rehearsal on
access), and appends a recall event to the ledger (cue set, so replay skips it).
"""
import math
import re
import time
from datetime import datetime, timedelta, timezone

from ..db import pgvector_literal
from . import cues, reconcile

RRF_K = 60
OVERFETCH = 50
BFS_HOPS = 2
BFS_NODES = 50
BFS_DECAY = 0.5
CARD_CHARS = 1600  # ~400 tokens at the codebase's chars/4 heuristic
COMMAND_BOOST = 1.5
CURRENTNESS_BOOST = 1.2
BFS_BUDGET_S = 0.25
# ACT-R fan effect: association S_ji = S - ln(fan_j). A tag shared by many
# rows spreads ~nothing to each (cue overload); a rare shared tag binds
# hard. Overloaded glue tags sink themselves negative — no special-casing.
FAN_S = 2.0
# ACT-R retrieval noise: P = logistic((A - tau)/s). Sharp near the floor,
# saturating away from it. s = 0.1 is our guess (literature: fitted ~0.4
# in log-odds units on lab tasks; ours rescales a 0..1 blend instead).
CONFIDENCE_S = 0.1
# REFERENCE resolution: how far back "that X we discussed" can reach (the
# correction pool uses 5; references reach a little further), and the shell
# words that frame a reference without naming anything (stripped before
# overlap so "discussed" never counts as content evidence).
REFERENCE_WINDOW = 10
REFERENCE_SHELL_WORDS = frozenset({
    "use", "using", "used", "like", "discussed", "discuss", "discussion",
    "mentioned", "mention", "said", "say", "saying", "told", "talked",
    "talk", "talking", "same", "again",
})
_THAT_NOUN_RE = re.compile(r"\bthat\s+([A-Za-z][\w/-]{1,40})", re.IGNORECASE)
_THE_SAME_NOUN_RE = re.compile(
    r"\bthe same\s+([A-Za-z][\w/-]{1,40})", re.IGNORECASE
)
_THOSE_THESE_NOUN_RE = re.compile(
    r"\b(those|these)\s+([A-Za-z][\w/-]{1,40})", re.IGNORECASE
)
# Plural referents resolve to ALL matching recent candidates. Detected here,
# not in the classifier: bare "they"/"them" stay on their current cue path
# (adding pronoun detection to cues.py would re-route QUESTION/STATEMENT
# queries); they resolve plurally when the query already classifies
# REFERENCE ("use them as we discussed").
_PLURAL_RE = re.compile(
    r"\b(they|them|their|theirs|those|these)\b", re.IGNORECASE
)


def _legs_sql(tiered: bool) -> str:
    tier = "AND tier = ANY(%s)" if tiered else ""
    return f"""
SELECT id, leg, rnk FROM (
  SELECT id, 'v' AS leg, row_number() OVER (ORDER BY d) AS rnk FROM (
    SELECT id, embedding <=> %s::vector AS d FROM memories
    WHERE owner = %s AND valid_to IS NULL AND NOT quarantined
      AND NOT ranked_out AND embedding IS NOT NULL {tier}
    ORDER BY d LIMIT {OVERFETCH}
  ) v
  UNION ALL
  SELECT id, 'f' AS leg, row_number() OVER (ORDER BY r DESC) AS rnk FROM (
    -- 'english' is load-bearing, not a default: stemming + stopwords let
    -- "What is the vault code?" hit (proven: 'simple' misses it, stopwords
    -- AND-mandatory). Non-English rides the multilingual vector leg.
    SELECT id, ts_rank(to_tsvector('english', content),
      plainto_tsquery('english', %s)) AS r FROM memories
    WHERE owner = %s AND valid_to IS NULL AND NOT quarantined
      AND NOT ranked_out
      AND to_tsvector('english', content) @@ plainto_tsquery('english', %s)
      {tier}
    ORDER BY r DESC LIMIT {OVERFETCH}
  ) f
  UNION ALL
  SELECT id, 'a' AS leg, row_number() OVER (
    ORDER BY assoc DESC, salience DESC, utility DESC) AS rnk FROM (
    -- Fan-normalized association: each row scores its STRONGEST shared
    -- tag (max over S - ln(fan)); fan counts live owner rows carrying
    -- the query tags. Specific overlap outranks mush overlap even at
    -- lower salience; salience/utility break assoc ties as before.
    SELECT m.id, m.salience, m.utility,
      max({FAN_S} - ln(tc.n)) AS assoc
    FROM memories m
    JOIN LATERAL unnest(m.tags) AS t ON t = ANY(%s)
    JOIN (SELECT t AS tag, count(*) AS n FROM memories, unnest(tags) t
          WHERE owner = %s AND valid_to IS NULL AND t = ANY(%s)
          GROUP BY t) tc ON tc.tag = t
    WHERE m.owner = %s AND m.valid_to IS NULL AND NOT m.quarantined
      AND NOT m.ranked_out {tier}
    GROUP BY m.id, m.salience, m.utility
    ORDER BY assoc DESC, m.salience DESC, m.utility DESC LIMIT {OVERFETCH}
  ) a
  UNION ALL
  SELECT id, 'e' AS leg, row_number() OVER (
    ORDER BY salience DESC, utility DESC) AS rnk FROM (
    -- Entity leg: query words hitting scribe subject/object slots. Same
    -- slots the linker wires, so retrieval and graph agree on what an
    -- entity is. Salience/utility order: the slot hit is binary.
    SELECT id, salience, utility FROM memories
    WHERE owner = %s AND valid_to IS NULL AND NOT quarantined
      AND NOT ranked_out
      AND (lower(btrim(subject)) = ANY(%s)
        OR lower(btrim("object")) = ANY(%s))
      {tier}
    ORDER BY salience DESC, utility DESC LIMIT {OVERFETCH}
  ) e
) u"""


def _rrf(rows: list[dict]) -> dict[str, dict]:
    fused: dict[str, dict] = {}
    for r in rows:
        mid = str(r["id"])
        slot = fused.setdefault(mid, {"score": 0.0, "legs": {}})
        slot["score"] += 1.0 / (RRF_K + r["rnk"])
        slot["legs"][r["leg"]] = r["rnk"]
    return fused


async def check_intentions(db, owner: str, entities: list[str]) -> list[dict]:
    """Fire pending intentions whose time_cue passed or event_cue overlaps."""
    clauses = ["(time_cue IS NOT NULL AND time_cue <= now())"]
    params: list = [owner]
    for e in entities[:12]:
        clauses.append(r"(event_cue IS NOT NULL AND event_cue ILIKE %s ESCAPE '\')")
        lit = e.lstrip("#@").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params.append(f"%{lit}%")
    rows = await db.fetch(
        "UPDATE intentions SET status = 'fired', fired_at = now() "
        f"WHERE owner = %s AND status = 'pending' AND ({' OR '.join(clauses)}) "
        "RETURNING id, content, event_cue, time_cue",
        tuple(params),
    )
    return [
        {
            "id": str(r["id"]), "content": r["content"],
            "event_cue": r["event_cue"],
            "time_cue": r["time_cue"].isoformat() if r["time_cue"] else None,
        }
        for r in rows
    ]


async def _bfs(db, owner: str, seeds: list[str], deadline: float) -> dict[str, dict]:
    """2-hop walk over memory_links, both directions (one row per
    association). Quarantined/superseded/ranked-out rows are never entered:
    the join filters them before traversal, so links cannot leak poison or
    retired rows into hits. Only the deliberate probe path sees ranked-out."""
    act = {s: 1.0 for s in seeds}
    found: dict[str, dict] = {}
    frontier = list(seeds)
    for _ in range(BFS_HOPS):
        if not frontier or time.monotonic() > deadline:
            break
        rows = await db.fetch(
            "SELECT l.src, l.dst, l.relation, l.weight, "
            "ms.valid_to AS s_valid, ms.quarantined AS s_quar, "
            "ms.ranked_out AS s_rank, "
            "md.valid_to AS d_valid, md.quarantined AS d_quar, "
            "md.ranked_out AS d_rank "
            "FROM memory_links l "
            "JOIN memories ms ON ms.id = l.src "
            "JOIN memories md ON md.id = l.dst "
            "WHERE l.owner = %s "
            "AND (l.src = ANY(%s::uuid[]) OR l.dst = ANY(%s::uuid[]))",
            (owner, frontier, frontier),
        )
        frontier = []
        for r in rows:
            src, dst = str(r["src"]), str(r["dst"])
            if src in act and dst not in act:
                known, other = src, dst
                dead = r["d_valid"] is not None or r["d_quar"] or r["d_rank"]
            elif dst in act and src not in act:
                known, other = dst, src
                dead = r["s_valid"] is not None or r["s_quar"] or r["s_rank"]
            else:
                continue  # cycle guard (both ends already visited)
            if dead:
                continue  # never traverse into dead, quarantined, or ranked-out rows
            a = act[known] * BFS_DECAY * float(r["weight"] or 1.0)
            act[other] = a
            found[other] = {"act": a, "via": r["relation"], "from": known}
            frontier.append(other)
            if len(act) >= BFS_NODES + len(seeds):
                break
    return found


def _confidence(fused: list[tuple[str, dict]], query: str,
                rows: dict[str, dict], top1cos: float) -> tuple[float, float]:
    """0.4 margin + 0.4 word coverage + 0.2 top-1 cosine (R2: ranks alone
    cannot separate a known single-leg fact from best-of-a-bad-lot noise;
    absolute similarity + word overlap can)."""
    if not fused:
        return 0.0, 0.0
    top1 = fused[0][1]["score"]
    top2 = fused[1][1]["score"] if len(fused) > 1 else 0.0
    margin = max(0.0, (top1 - top2) / top1) if top1 > 0 else 0.0
    words = cues.coverage_entities(query)
    if not words:
        cov = 0.5
    else:
        bag = " ".join(
            " ".join((rows[m]["tags"] or [])) + " " + (rows[m]["content"] or "")[:500]
            for m, _ in fused[:8] if m in rows
        ).lower()
        cov = sum(1 for w in words if w in bag) / len(words)
    conf = 0.4 * margin + 0.4 * cov + 0.2 * max(0.0, min(1.0, top1cos))
    return round(conf, 3), round(margin, 3)


def retrieval_probability(activation: float, floor: float) -> float:
    """ACT-R retrieval probability P = 1/(1 + e^(-(A - tau)/s)). The R2
    blend is the activation A; the confidence floor is the threshold tau.
    Monotonic rescaling: abstain boundary identical (P < 0.5 iff A < tau),
    numbers gain probabilistic semantics."""
    return 1.0 / (1.0 + math.exp(-(activation - floor) / CONFIDENCE_S))


def cluster_hits(hits: list[dict]) -> list[dict]:
    """Rule Completer: group hits that share a tag (union-find, no LLM).

    Each cluster carries its label (most-shared tag), member ids ordered by
    score, and size. Singletons keep their own cluster so every hit is
    covered exactly once. Kind-namespace words never group (the same mush
    doctrine as link formation: shared "preference" is not a topic), and a
    hit's own kind never groups it either (emergent kinds included).
    Pure function of the hit list: deterministic and fixture-testable."""
    parent = list(range(len(hits)))
    tag_first: dict[str, int] = {}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def _real(h):
        own = (h.get("kind") or "").strip().lower()
        return [t for t in (h.get("tags") or [])
                if t not in reconcile.STOP_TAGS and t != own]

    for i, h in enumerate(hits):
        for t in _real(h):
            if t in tag_first:
                parent[find(i)] = find(tag_first[t])
            else:
                tag_first[t] = i
    groups: dict[int, list[int]] = {}
    for i in range(len(hits)):
        groups.setdefault(find(i), []).append(i)
    clusters = []
    for members in groups.values():
        members.sort(key=lambda i: -hits[i].get("score", 0.0))
        counts: dict[str, int] = {}
        for i in members:
            for t in _real(hits[i]):
                counts[t] = counts.get(t, 0) + 1
        label = max(counts, key=lambda t: (counts[t], t)) if counts else "ungrouped"
        clusters.append({
            "label": label,
            "ids": [hits[i]["id"] for i in members],
            "size": len(members),
        })
    order = {h["id"]: h.get("score", 0.0) for h in hits}
    clusters.sort(key=lambda c: -max(order[i] for i in c["ids"]))
    return clusters


QUERY_STOPS = frozenset(
    "what when where which who whom whose why how does did done are was "
    "were the and for with from that this these those then than them they "
    "you your our have has had can could should would will".split()
)


def query_entities(query: str) -> list[str]:
    """Entity-ish tokens for the 'e' leg: lowercase alpha words, stops
    removed (query stops + linker entity stops: owner/user/system never
    boost, or every owner row wins every query)."""
    from .linker import STOP_ENTITIES
    out = []
    for w in re.findall(r"[a-z]+", (query or "").lower()):
        if len(w) > 2 and w not in QUERY_STOPS and w not in STOP_ENTITIES \
                and w not in out:
            out.append(w)
    return out


def _why(legs: dict, cue_type: str) -> str:
    parts = []
    if "v" in legs:
        parts.append(f"vector #{legs['v']}")
    if "f" in legs:
        parts.append(f"lexical #{legs['f']}")
    if "a" in legs:
        parts.append(f"tag #{legs['a']}")
    if "e" in legs:
        parts.append(f"entity #{legs['e']}")
    return f"{cue_type} -> {' + '.join(parts)}"


async def _bump_access(db, ids: list[str]) -> None:
    """Rehearsal on retrieval: serving a hit is retrieval PRACTICE (the
    testing effect), the strongest rehearsal there is — access_count,
    last_access, retrieval strength (utility), and memory stability
    (each serve adds a day, to 365) all move."""
    if ids:
        await db.execute(
            "UPDATE memories SET access_count = access_count + 1, "
            "last_access = now(), "
            "utility = LEAST(1.0, utility + 0.15), "
            "stability = LEAST(365.0, stability + 1.0) "
            "WHERE id = ANY(%s::uuid[])",
            (ids,),
        )


async def register_reminder(db, owner: str, draft: dict) -> dict | None:
    """Shared write/recall registration; idempotent on pending content."""
    if not draft or not draft["content"]:
        return None
    dup = await db.fetchrow(
        "SELECT id, content, event_cue, time_cue FROM intentions "
        "WHERE owner = %s AND status = 'pending' AND content = %s",
        (owner, draft["content"]),
    )
    if dup:  # re-uttered reminder (or a write/recal double path): one row
        return {
            "id": str(dup["id"]), "content": dup["content"],
            "event_cue": dup["event_cue"],
            "time_cue": dup["time_cue"].isoformat() if dup["time_cue"] else None,
            "duplicate": True,
        }
    delta = timedelta(days=draft["days"], hours=draft["hours"])
    time_cue = (
        datetime.now(timezone.utc) + delta if delta.total_seconds() > 0 else None
    )
    row = await db.execute_returning(
        "INSERT INTO intentions (owner, content, event_cue, time_cue) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (owner, draft["content"], draft["event_cue"], time_cue),
    )
    return {
        "id": str(row["id"]), "content": draft["content"],
        "event_cue": draft["event_cue"],
        "time_cue": time_cue.isoformat() if time_cue else None,
    }


def _card(identity: list[dict], hits: list[dict], abstain: bool) -> str | None:
    if abstain and not identity:
        return None
    lines = []
    for r in identity:
        lines.append(f"- {r['content']}"[:200])
    head = "# who you are\n" + "\n".join(lines) if lines else ""
    body = []
    if not abstain:
        for h in hits:
            if h["tier"] == "identity":
                continue
            body.append(f"- [{h['tier']}/{h['kind']}] {h['summary']} ({h['why']})")
    chunks = [c for c in (head, "# context\n" + "\n".join(body) if body else "") if c]
    tags: list[str] = []
    for h in hits:
        tags += [t for t in h["tags"] if t not in tags]
    if tags[:6]:
        chunks.append("probe deeper: " + " ".join(f"#{t}" for t in tags[:6]))
    text = "\n\n".join(chunks)
    if len(text) <= CARD_CHARS:
        return text
    cut = text.rfind("\n", 0, CARD_CHARS)
    if cut <= 0:
        cut = CARD_CHARS  # one giant line: hard cut is the only option
    return text[:cut].rstrip() + "\n…"


async def _contiguity(db, owner: str, winner: dict) -> list[str]:
    """Winner + same-session episodic neighbours in logical turn order
    (contiguity). NEVER created_at: under concurrency commit order is not
    narrative order (same repair as the temporal chain)."""
    path = [str(winner["id"])]
    session = (winner.get("source") or {}).get("session")
    if not session:
        return path
    rows = await db.fetch(
        "SELECT id, source, created_at FROM memories WHERE owner = %s "
        "AND tier = 'episodic' AND valid_to IS NULL AND NOT quarantined "
        "AND NOT ranked_out AND source->>'session' = %s",
        (owner, session),
    )
    if len(rows) < 2:
        return path
    rows.sort(key=lambda r: (
        reconcile._turn_of(r["source"])
        if reconcile._turn_of(r["source"]) is not None
        else float("inf"),
        r["created_at"],
    ))
    idx = next((i for i, r in enumerate(rows)
                if str(r["id"]) == path[0]), None)
    if idx is None:
        return path
    if idx > 0:
        path.insert(0, str(rows[idx - 1]["id"]))
    if idx < len(rows) - 1:
        path.append(str(rows[idx + 1]["id"]))
    return path


async def _recall_event(db, owner: str, session_id: str, query: str, cue: cues.Cue,
                        mode: str, confidence: float, abstain: bool,
                        n: int, latency_ms: int) -> None:
    from psycopg.types.json import Json

    await db.execute(
        "INSERT INTO memory_events (owner, session_id, utterance, "
        "observer_verdict, scribe_action, cue, latency_ms, tokens) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            owner, session_id, query,
            Json({"recall": True, "confidence": confidence, "abstain": abstain}),
            Json({"op": "RECALL", "mode": mode, "n": n}),
            Json({"type": cue.type, "entities": cue.entities, "policy": cue.policy}),
            latency_ms, 0,
        ),
    )


def _is_plural_reference(query: str) -> bool:
    """Plural referent markers: plural pronouns and plural demonstratives."""
    return bool(_PLURAL_RE.search(query))


def _reference_hints(query: str, cue: cues.Cue
                   ) -> tuple[list[str], list[str], list[str], dict[str, str]]:
    """Split REFERENCE evidence into explicit (#/@/quoted spans), definite
    nouns (that-N / the-same-N / those-N / these-N), and soft content words.
    Stopwords can never be definite nouns ("that we discussed" points at
    nothing named). The fourth element maps each definite noun to its
    determiner label for match narration."""
    explicit = list(cue.entities)
    nouns: list[tuple[str, str]] = [
        (n, "that-N") for n in _THAT_NOUN_RE.findall(query)
    ] + [
        (n, "that-N") for n in _THE_SAME_NOUN_RE.findall(query)
    ] + [
        (n, f"{det.lower()}-N")
        for det, n in _THOSE_THESE_NOUN_RE.findall(query)
    ]
    definite: list[str] = []
    det_of: dict[str, str] = {}
    for n, label in nouns:
        if n.lower() in cues.STOPWORDS or n.lower() in det_of:
            continue
        definite.append(n)
        det_of[n.lower()] = label
    seen = {e.lower().lstrip("#@") for e in explicit}
    seen |= {n.lower() for n in definite}
    soft = [w for w in cues.coverage_entities(query)
            if w not in REFERENCE_SHELL_WORDS and w not in seen]
    return explicit, definite, soft, det_of


def _fold_plural(word: str) -> str:
    """Crude singularization so "those DBs" matches a stored DB ("DBs" is
    too short for a stemmer to matter; guard the ss/us endings)."""
    w = word.lower()
    if len(w) >= 3 and w.endswith("s") and not w.endswith(("ss", "us")):
        return w[:-1]
    return w


def _referent_matches(hint: str, text: str, tags: list[str]) -> bool:
    h = hint.lower().lstrip("#@").strip()
    if not h:
        return False
    # Single tokens match on word boundaries ("db" must not fire inside
    # "redblueberries"); multi-word phrases fall back to substring, where
    # the embedded spaces already prevent inside-word matches.
    words = set(re.findall(r"[\w/-]+", text.lower()))

    def _hit(x: str) -> bool:
        if x in tags:
            return True
        if " " in x:
            return x in text.lower()
        return x in words

    if _hit(h):
        return True
    fh = _fold_plural(h)
    if fh != h and _hit(fh):
        return True
    return any(_fold_plural(t) in (h, fh) for t in tags)


def _referent_label(exp: str | None, dfn: str | None, overlap: int,
                    det_of: dict[str, str]) -> str:
    if exp:
        return f"explicit '{exp}'"
    if dfn:
        return f"{det_of.get(dfn.lower(), 'that-N')} '{dfn.lower()}'"
    return f"overlap {overlap} word{'s' if overlap > 1 else ''}"


async def _resolve_referents(db, owner: str, session_id: str,
                             query: str, cue: cues.Cue, plural: bool = False
                             ) -> tuple[list[dict], bool]:
    """REFERENCE resolution: "that DB we discussed" points at a recent
    session episode. Window: last REFERENCE_WINDOW live episodic rows in
    this session, logical-turn order (never created_at: commit order is not
    narrative order), null turns last. Explicit entities and definite nouns
    constrain (a pointing expression with no target is an honest abstain,
    not a recency guess); soft words rank within; score ties break by
    salience, then recency. Zero-evidence pronouns take the most recent row
    (most salient = last mentioned).

    Plural queries ("they", "those DBs", "them") resolve to ALL matching
    recent candidates instead of the top one; the primary (first) is still
    the tie-break winner. Returns (referents, tie_broke): tie_broke is True
    when recency decided the primary among contenders, and the story then
    names the picked turn."""
    rows = await db.fetch(
        "SELECT id, content, summary, tags, salience, source, created_at "
        "FROM memories WHERE owner = %s AND tier = 'episodic' "
        "AND valid_to IS NULL AND NOT quarantined AND NOT ranked_out "
        "AND source->>'session' = %s",
        (owner, session_id),
    )
    if not rows:
        return [], False

    def _rkey(r):
        t = reconcile._turn_of(r["source"])
        ts = r["created_at"].timestamp() if r["created_at"] else 0.0
        return (t is None, -(t or 0), -ts)

    window = sorted(rows, key=_rkey)[:REFERENCE_WINDOW]
    explicit, definite, soft, det_of = _reference_hints(query, cue)
    scored = []
    for r in window:
        text = f"{r['content'] or ''} {r['summary'] or ''}".lower()
        tags = [(t or "").lower() for t in (r["tags"] or [])]
        exp = next(
            (e for e in explicit if _referent_matches(e, text, tags)), None)
        dfn = next(
            (n for n in definite if _referent_matches(n, text, tags)), None)
        overlap = sum(1 for w in soft if _referent_matches(w, text, tags))
        score = (3 if exp else 0) + (2 if dfn else 0) + overlap
        scored.append((r, score, exp, dfn, overlap))
    pool = scored
    if explicit:
        pool = [s for s in pool if s[2] is not None]
        if not pool:
            return [], False  # #/@/quoted target absent from this session
    if definite:
        pool = [s for s in pool if s[3] is not None]
        if not pool:
            return [], False  # "that N" names something never said here
    order = {str(s[0]["id"]): i for i, s in enumerate(scored)}

    def _skey(s):
        return (-s[1], -(float(s[0]["salience"] or 0.0)),
                order[str(s[0]["id"])])

    def _ties(a, b) -> bool:
        return (a[1] == b[1] and
                float(a[0]["salience"] or 0.0) ==
                float(b[0]["salience"] or 0.0))

    def _pack(s, match: str) -> dict:
        row = s[0]
        content = row["content"] or ""
        return {
            "id": str(row["id"]), "content": content,
            "summary": (row["summary"] or content)[:300],
            "tags": row["tags"] or [], "match": match,
            "turn": reconcile._turn_of(row["source"]),
        }

    fallback = all(s[1] == 0 for s in pool)
    if not plural:
        if fallback:
            win = min(pool, key=lambda s: order[str(s[0]["id"])])
            return [_pack(win, "recency fallback")], len(pool) >= 2
        pool.sort(key=_skey)
        win = pool[0]
        tie = len(pool) >= 2 and _ties(pool[0], pool[1])
        return [_pack(win, _referent_label(win[2], win[3], win[4], det_of)),
                ], tie
    if fallback:
        wins = sorted(pool, key=lambda s: order[str(s[0]["id"])])
        return [_pack(s, "recency fallback") for s in wins], len(pool) >= 2
    matched = [s for s in pool if s[1] > 0]
    matched.sort(key=_skey)
    tie = len(matched) >= 2 and _ties(matched[0], matched[1])
    return [_pack(s, _referent_label(s[2], s[3], s[4], det_of))
            for s in matched], tie


async def recall(*, db, embedder, owner: str, query: str, session_id: str,
                 k: int, tiers: list[str] | None, settings,
                 include_identity: bool = True) -> dict:
    t0 = time.monotonic()
    cue = cues.classify(query)
    fired = await check_intentions(db, owner, cue.entities)
    registered = None
    if cue.type == "COMMAND":
        draft = cues.parse_reminder(query)
        if draft:
            registered = await register_reminder(db, owner, draft)
    if cue.replay:
        out = await _replay(db, owner, session_id, settings)
    else:
        out = await _ranked(db, embedder, owner, query, cue, k, tiers,
                            settings, include_identity,
                            session_id=session_id)
    out["fired_intentions"] = fired
    out["registered_intention"] = registered
    out["cue"] = {"type": cue.type, "entities": cue.entities, "policy": cue.policy}
    reconcile.note_active(owner, session_id, [h["id"] for h in out["hits"]])
    latency_ms = int((time.monotonic() - t0) * 1000)
    out["latency_ms"] = latency_ms
    await _recall_event(db, owner, session_id, query, cue, out["mode"],
                        out["confidence"], out["abstain"], len(out["hits"]),
                        latency_ms)
    return out


async def _ranked(db, embedder, owner, query, cue, k, tiers, settings,
                include_identity: bool = True, session_id: str = "") -> dict:
    referent: dict | None = None
    referents: list[dict] = []
    tie_broke = False
    plural = False
    eff_query = query
    extra_tags: list[str] = []
    if cue.type == "REFERENCE":
        plural = _is_plural_reference(query)
        referents, tie_broke = await _resolve_referents(
            db, owner, session_id, query, cue, plural=plural)
        if not referents:
            identity = []
            if include_identity:
                identity = await db.fetch(
                    "SELECT id, content FROM memories WHERE owner = %s "
                    "AND tier = 'identity' "
                    "AND valid_to IS NULL AND NOT quarantined "
                    "ORDER BY salience DESC LIMIT 5",
                    (owner,),
                )
            return {
                "mode": "ranked",
                "card": _card(identity, [], True),
                "hits": [], "clusters": [],
                "confidence": 0.0, "abstain": True,
                "margin": 0.0, "path": [], "candidates_matched": 0,
                "story": ("REFERENCE: no referent in recent session episodic "
                          "memory — abstained"),
                "referent": None,
                "referents": [],
            }
        referent = referents[0]
        if plural:
            joined = " | ".join(r["content"] for r in referents)
            eff_query = f"{query}\nReferents: {joined}"[:2000]
            extra_tags = list(dict.fromkeys(
                t for r in referents for t in r["tags"]))
        else:
            eff_query = f"{query}\nReferent: {referent['content']}"[:2000]
            extra_tags = referent["tags"]
    vec, _ = await embedder.embed(eff_query, is_query=True)
    tags = reconcile._norm_tags(
        [e[1:] for e in cue.entities if e.startswith(("#", "@"))]
        + extra_tags)
    tiered = bool(tiers)
    params: list = [pgvector_literal(vec), owner]
    if tiered:
        params.append(tiers)
    params += [eff_query, owner, eff_query]
    if tiered:
        params.append(tiers)
    # 'a' leg textual order: tags, owner, tags, owner (+tiers).
    params += [tags, owner, tags, owner]
    if tiered:
        params.append(tiers)
    # 'e' leg textual order: owner, words, words (+tiers).
    words = query_entities(eff_query)
    params += [owner, words, words]
    if tiered:
        params.append(tiers)
    rows = await db.fetch(_legs_sql(tiered), tuple(params))
    fused = _rrf(rows)
    candidates_matched = len({str(r["id"]) for r in rows})
    identity: list = []
    if include_identity:
        identity = await db.fetch(
            "SELECT id, content FROM memories WHERE owner = %s "
            "AND tier = 'identity' "
            "AND valid_to IS NULL AND NOT quarantined "
            "ORDER BY salience DESC LIMIT 5",
            (owner,),
        )
    # Identity bypasses ranking entirely: card header only, never a hit.
    # Rehearsal follows service: unserved identity is not bumped.
    ordered = sorted(fused.items(), key=lambda kv: -kv[1]["score"])
    fetch_ids = [m for m, _ in ordered[: k + 8]]
    grown: dict[str, dict] = {}
    if fetch_ids:
        grown = await _bfs(db, owner, fetch_ids[:k] or fetch_ids,
                           time.monotonic() + BFS_BUDGET_S)
    want = list(dict.fromkeys(fetch_ids + list(grown)))
    by_id = {}
    if want:
        for r in await db.fetch(
            "SELECT id, tier, kind, content, summary, tags, trust, salience, "
            "utility, source, created_at, principle, supersedes FROM memories "
            "WHERE id = ANY(%s::uuid[])",
            (want,),
        ):
            by_id[str(r["id"])] = r
    # Currentness: rows that superseded another row are newer truth than
    # rows that never updated. Small boost, applied before BFS growth so
    # current truth also seeds stronger association spread.
    for mid, slot in fused.items():
        row = by_id.get(mid)
        if row is not None and row.get("supersedes") is not None:
            slot["score"] *= CURRENTNESS_BOOST
    if cue.policy == "command":
        # Actionability emerges from the Scribe's principle field (rows that
        # carry a reusable rule), never from a fixed kind list: kinds are
        # emergent now, so no enumeration can name the actionable ones.
        for mid, slot in fused.items():
            row = by_id.get(mid)
            if row and (row["principle"] or "").strip():
                slot["score"] *= COMMAND_BOOST
        ordered = sorted(fused.items(), key=lambda kv: -kv[1]["score"])
    for mid, g in grown.items():
        if mid not in fused and g["act"] >= 0.25 and mid in by_id:
            fused[mid] = {"score": g["act"] * 0.01, "legs": {},
                          "via": f"associated via {g['via']}"}
    ordered = sorted(fused.items(), key=lambda kv: -kv[1]["score"])
    top1cos = 0.0
    if ordered:
        dist = await db.fetchval(
            "SELECT embedding <=> %s::vector FROM memories WHERE id = %s::uuid",
            (pgvector_literal(vec), ordered[0][0]),
        )
        top1cos = max(0.0, 1.0 - float(dist or 1.0))
    confidence, margin = _confidence(ordered, eff_query, by_id, top1cos)
    if not ordered:
        prob = 0.0  # no evidence at all: zero, not the logistic floor
    else:
        prob = retrieval_probability(confidence, settings.confidence_floor)
    abstain = prob < 0.5  # unrounded: boundary exactly A < tau, no sliver
    confidence = round(prob, 3)
    hits = []
    for mid, slot in ordered[:k]:
        row = by_id.get(mid)
        if row is None:
            continue
        text = row["content"] or ""
        hits.append({
            "id": mid, "tier": row["tier"], "kind": row["kind"],
            "summary": (row["summary"] or text)[:300], "tags": row["tags"] or [],
            "score": round(slot["score"], 4), "trust": row["trust"],
            "why": slot.get("via") or _why(slot["legs"], cue.type),
        })
    await _bump_access(db, [h["id"] for h in hits] + [str(r["id"]) for r in identity])
    path: list[str] = []
    if hits and not abstain:
        winner = by_id.get(hits[0]["id"])
        if winner is not None:
            path = await _contiguity(db, owner, winner)
    assoc = sum(1 for h in hits if (h.get("why") or "").startswith("associated"))
    if abstain:
        story = (f"{cue.type}: no confident match "
                 f"({confidence:.2f} < {settings.confidence_floor:.2f}) — abstained")
    elif hits:
        story = (f"{cue.type}: {len(hits)} hit(s), top {hits[0]['why']}, "
                 f"{assoc} associated, path of {len(path)}, "
                 f"confidence {confidence:.2f}")
    else:
        story = f"{cue.type}: store is empty for this cue — abstained"
    out = {
        "mode": "ranked", "card": _card(identity, hits, abstain),
        "hits": hits, "clusters": cluster_hits(hits),
        "confidence": confidence, "abstain": abstain,
        "margin": margin, "path": path, "candidates_matched": candidates_matched,
        "story": story,
    }
    if referent is not None:
        head, _, tail = story.partition(": ")
        turn = referent["turn"]
        turn_label = f"turn {turn}" if turn is not None else "most recent"
        if plural:
            ids = ", ".join(r["id"][:8] for r in referents)
            n = len(referents)
            word = "match" if n == 1 else "matches"
            how = "tie-break" if tie_broke else "primary"
            out["story"] = (f"{head}: referents {ids} "
                            f"({n} {word}; {how} {turn_label}) — {tail}")
        elif tie_broke:
            out["story"] = (f"{head}: referent {referent['id'][:8]} "
                            f"({referent['match']}; tie-break {turn_label}) "
                            f"— {tail}")
        else:
            out["story"] = (f"{head}: referent {referent['id'][:8]} "
                            f"({referent['match']}) — {tail}")
        out["referent"] = {
            "id": referent["id"], "summary": referent["summary"],
            "match": referent["match"], "turn": referent["turn"],
        }
        out["referents"] = [
            {"id": r["id"], "summary": r["summary"], "match": r["match"],
             "turn": r["turn"]}
            for r in referents
        ]
    return out


async def _replay(db, owner: str, session_id: str, settings) -> dict:
    events = await db.fetch(
        "SELECT id, turn, utterance, scribe_action FROM memory_events "
        "WHERE owner = %s AND session_id = %s AND cue IS NULL "
        "AND utterance IS NOT NULL ORDER BY turn NULLS LAST, id LIMIT %s",
        (owner, session_id, settings.replay_n),
    )
    if not events:
        return {
            "mode": "replay", "card": None, "hits": [], "clusters": [],
            "timeline": [], "confidence": 0.0, "abstain": True,
            "margin": 0.0, "path": [], "candidates_matched": 0,
            "story": "RECENCY: session has no turns yet — nothing to replay",
        }
    mids: list[str] = []
    for e in events:
        for mid in ((e["scribe_action"] or {}).get("memory_ids") or []):
            if mid not in mids:
                mids.append(mid)
    by_id = {}
    if mids:
        for r in await db.fetch(
            "SELECT id, tier, kind, content, summary, tags, trust FROM memories "
            "WHERE id = ANY(%s::uuid[]) AND valid_to IS NULL AND NOT quarantined "
            "AND NOT ranked_out",
            (mids,),
        ):
            by_id[str(r["id"])] = r
    hits, timeline = [], []
    for e in events:
        kept = []
        for mid in ((e["scribe_action"] or {}).get("memory_ids") or []):
            row = by_id.get(mid)
            if row is None:
                continue
            kept.append((row["summary"] or row["content"])[:160])
            if mid not in {h["id"] for h in hits}:
                text = row["content"] or ""
                hits.append({
                    "id": mid, "tier": row["tier"], "kind": row["kind"],
                    "summary": (row["summary"] or text)[:300],
                    "tags": row["tags"] or [], "score": 1.0,
                    "trust": row["trust"], "why": f"replay turn {e['turn']}",
                })
        timeline.append({
            "turn": e["turn"], "utterance": (e["utterance"] or "")[:200],
            "kept": kept,
        })
    await _bump_access(db, [h["id"] for h in hits])
    lines = [f"{t['turn']}: {t['utterance']}" for t in timeline]
    kept_lines = [f"  -> {k}" for t in timeline for k in t["kept"]]
    card = "# session replay\n" + "\n".join(lines + kept_lines)
    return {
        "mode": "replay", "card": card[:CARD_CHARS], "hits": hits,
        "clusters": cluster_hits(hits), "timeline": timeline,
        "confidence": 1.0, "abstain": False, "margin": 1.0,
        "path": [h["id"] for h in hits], "candidates_matched": len(events),
        "story": (f"RECENCY: replayed {len(events)} session turn(s), "
                  f"{len(hits)} kept — no ranking"),
    }

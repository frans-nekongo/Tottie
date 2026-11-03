"""GET /graph — nodes + links for the brain view (cap ~300, tier filter).
GET /memories — row browser for the pending strip (quarantine filter).
Auth is wired in main.py (router-level dependency), same as /write.
"""
from fastapi import APIRouter, HTTPException, Query, Request, status

router = APIRouter()

TIERS = {"identity", "episodic", "knowledge", "procedural"}
GRAPH_CAP = 300
# The brain must show births, not just celebrities: salience-only top-N
# buries fresh low-salience rows past the cap (owner_local holds ~990).
# 250 salient + 50 newest keeps the cap while guaranteeing a new memory
# appears the instant it lands.
GRAPH_SALIENT = 250
GRAPH_FRESH = 50


@router.get("/graph")
async def get_graph(
    request: Request,
    owner: str = Query(""),
    tiers: str = Query(""),
) -> dict:
    settings = request.app.state.settings
    want = [t for t in tiers.split(",") if t] or None
    if want is not None:
        bad = [t for t in want if t not in TIERS]
        if bad:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"unknown tiers {bad}; want subset of {sorted(TIERS)}",
            )
    db = request.app.state.db
    who = owner or settings.owner
    tier_clause = "" if want is None else "AND tier = ANY(%s)"
    tier_params: tuple = () if want is None else (want,)
    cols = (
        "SELECT id, content, tier, tags, salience, created_at, "
        "quarantined, ranked_out FROM memories WHERE owner = %s "
        "AND valid_to IS NULL " + tier_clause
    )
    salient = await db.fetch(
        cols + " ORDER BY salience DESC LIMIT %s",
        (who, *tier_params, GRAPH_SALIENT),
    )
    fresh = await db.fetch(
        cols + " ORDER BY created_at DESC LIMIT %s",
        (who, *tier_params, GRAPH_FRESH),
    )
    seen: set[str] = set()
    rows = []
    for r in list(salient) + list(fresh):
        rid = str(r["id"])
        if rid not in seen:
            seen.add(rid)
            rows.append(r)
    ids = [str(r["id"]) for r in rows]
    links = []
    if ids:
        links = await db.fetch(
            "SELECT src, dst, relation, weight, reason FROM memory_links "
            "WHERE owner = %s AND src = ANY(%s::uuid[]) "
            "AND dst = ANY(%s::uuid[])",
            (who, ids, ids),
        )
    return {
        "nodes": [{
            "id": str(r["id"]), "label": (r["content"] or "")[:80],
            "tier": r["tier"], "tags": r["tags"] or [],
            "salience": r["salience"],
            "created": r["created_at"].isoformat() if r["created_at"] else None,
            "quarantined": r["quarantined"],
            "ranked_out": r["ranked_out"],
        } for r in rows],
        "links": [{
            "source": str(l["src"]), "target": str(l["dst"]),
            "relation": l["relation"], "weight": l["weight"],
            "reason": l["reason"] or l["relation"],
        } for l in links],
    }


@router.get("/memories")
async def get_memories(
    request: Request,
    owner: str = Query(""),
    quarantined: bool | None = Query(None),
    kind: str = Query(""),
    id: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    settings = request.app.state.settings
    db = request.app.state.db
    if id:
        row = await db.fetchrow(
            "SELECT id, tier, kind, content, tags, salience, trust, "
            "quarantined, created_at FROM memories WHERE id = %s::uuid "
            "AND owner = %s",
            (id, owner or settings.owner),
        )
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown memory id")
        rows = [row]
    else:
        clauses = ["owner = %s", "valid_to IS NULL"]
        params: list = [owner or settings.owner]
        if quarantined is not None:
            clauses.append("quarantined = %s")
            params.append(quarantined)
        if kind:
            clauses.append("kind = %s")
            params.append(kind)
        rows = await db.fetch(
            "SELECT id, tier, kind, content, tags, salience, trust, quarantined, "
            "created_at FROM memories WHERE " + " AND ".join(clauses) +
            " ORDER BY created_at DESC LIMIT %s",
            tuple(params + [limit]),
        )
    out = []
    for r in rows:
        out.append({
            "id": str(r["id"]), "tier": r["tier"], "kind": r["kind"],
            "content": r["content"], "tags": r["tags"] or [],
            "salience": r["salience"], "trust": r["trust"],
            "quarantined": r["quarantined"],
            "created": r["created_at"].isoformat() if r["created_at"] else None,
        })
    return {"owner": owner or settings.owner, "memories": out}

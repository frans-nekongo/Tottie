"""Offline link repair: recompute temporal chains + tag links for rows that
predate linking v2 (or were written while it was broken). Idempotent:
existing pairs are never duplicated. Bounded: TAG scan mirrors the live
cap, so it cannot explode a big store. CLI: tottie.py relink.
"""
from .reconcile import STOP_TAGS

TAG_SCAN_CAP = 3
ROW_CAP = 500


async def relink(db, owner: str) -> dict:
    made = {"temporal": 0, "tag": 0}
    rows = await db.fetch(
        "SELECT id, tags, source, created_at FROM memories "
        "WHERE owner = %s AND valid_to IS NULL ORDER BY created_at, id "
        "LIMIT %s",
        (owner, ROW_CAP),
    )
    have = await db.fetch(
        "SELECT src, dst, relation FROM memory_links WHERE owner = %s",
        (owner,),
    )
    have_set = {(str(h["src"]), str(h["dst"]), h["relation"]) for h in have}
    prev_by_session: dict[str, dict] = {}
    for i, r in enumerate(rows):
        mid = str(r["id"])
        sess = (r["source"] or {}).get("session")
        if sess and sess in prev_by_session:
            p = prev_by_session[sess]
            if (mid, str(p["id"]), "temporal") not in have_set:
                await db.execute(
                    "INSERT INTO memory_links (owner, src, dst, relation, "
                    "weight, reason) VALUES (%s, %s::uuid, %s::uuid, "
                    "'temporal', 0.8, %s) ON CONFLICT "
                    "(owner, src, dst, relation) DO NOTHING",
                    (owner, mid, str(p["id"]),
                     f"session order: turn {(p['source'] or {}).get('turn', '?')} "
                     f"-> turn {(r['source'] or {}).get('turn', '?')} (relink)"),
                )
                made["temporal"] += 1
                have_set.add((mid, str(p["id"]), "temporal"))
        if sess:
            prev_by_session[sess] = r
        mine = set(r["tags"] or []) - STOP_TAGS
        if not mine:
            continue
        found = 0
        for o in rows[:i]:  # earlier rows only: one directed edge, like live
            if found >= TAG_SCAN_CAP:
                break
            shared = sorted(mine & (set(o["tags"] or []) - STOP_TAGS))
            if not shared:
                continue
            key = (mid, str(o["id"]), "tag")
            if key in have_set:
                continue
            await db.execute(
                "INSERT INTO memory_links (owner, src, dst, relation, weight, "
                "reason) VALUES (%s, %s::uuid, %s::uuid, 'tag', 1.0, %s) "
                "ON CONFLICT (owner, src, dst, relation) DO NOTHING",
                (owner, mid, str(o["id"]),
                 f"shared tag: {', '.join(shared)} (relink)"),
            )
            made["tag"] += 1
            have_set.add(key)
            found += 1
    return made

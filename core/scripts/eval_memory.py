#!/usr/bin/env python3
"""Frozen memory eval: the probe set from the multi-agent planning turn,
with pass/fail thresholds. Self-seeding: recall probes (1, 2, 4) seed
their own rows under owner 'evalseed' (cleaned before + after), so the
eval runs green on any store state — no ambient drill dependency (the
Nov 2026 wipe proved ambient state evaporates). Store-health checks
(5, 8, 9, 10) assert the live prod owners.

Checks:
  1. week_current — week probe tops Sun-Sat, no Monday rows
  2. g5_recall — keyword probe returns the G5 research
  3. nonsense_abstain — gibberish abstains
  4. entity_leg — Anna query fires the entity leg
  5. no_dups — zero live pairs above 0.98 per owner
  6. stages_present — latest write event carries stage timings
  7. accept_fast — /write 202s in under 2s (async accept holds)
  8. junk_free — curator sweep leaves zero rule-junk rows per owner
  9. topic_coverage — taxonomy sweep tags 100% of live rows per owner
  10. area_coverage — taxonomy sweep tags 100% areas per owner

Checks 8-9 run their sweeps inline first (idempotent): the eval
asserts the steady state, not the timing of the heartbeat.

Usage: ./venv/bin/python scripts/eval_memory.py (from core/)
Exit code = number of failures.
"""
import asyncio
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CORE = os.environ.get("TOTTIE_CORE_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("TOTTIE_API_TOKEN", "changeme-local-token")
FAILURES: list[str] = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def api(path, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        CORE + path, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def _seed_eval_owner():
    """Seed recall-probe rows under an isolated owner (direct insert:
    recall is what's asserted, not the write path). Cleaned first so
    reruns and crashes never stack duplicates."""
    import uuid

    from psycopg.types.json import Json

    from app.config import Settings
    from app.db import Database, pgvector_literal
    from app.embeddings import Embedder

    async def go():
        db = Database(Settings())
        await db.open()
        emb = Embedder(Settings())
        await db.execute(
            "DELETE FROM memory_links WHERE owner = 'evalseed'")
        await db.execute(
            "DELETE FROM memories WHERE owner = 'evalseed'")
        seeds = [
            ("Tracker week runs Sunday to Saturday.", "tracker", None,
             None),
            ("Tracker week ran Monday to Sunday with no carryover of "
             "extra runs.", "tracker", None, "retired"),
            ("Familiarity floor 0.55 gates candidates before NLI.",
             "familiarity", None, None),
            ("NLI slot indexing fix options ranked by cost.", "slot",
             None, None),
            ("Slot verify pass runs after the familiarity gate.",
             "slot", None, None),
            ("Anna birthday dinner is Friday at eight.", "Anna",
             "dinner", None),
            ("Ben cheers for Anna at the birthday dinner.", "Ben",
             "dinner", None),
        ]
        for content, subj, obj, dead in seeds:
            vec, _ = await emb.embed(content)
            await db.execute(
                'INSERT INTO memories (owner, tier, kind, subject, '
                '"object", content, trust, source, embedding, '
                "embedding_model, hash, valid_to) VALUES ('evalseed',"
                "'knowledge','fact',%s,%s,%s,'user_direct',%s,"
                "%s::vector,%s,%s,"
                + ("now()" if dead else "NULL") + ")",
                (subj, obj, content,
                 Json({"session": "evalseed", "turn": 0}),
                 pgvector_literal(vec), emb.model_name,
                 uuid.uuid4().hex),
            )
        await db.close()

    asyncio.run(go())


def _clean_eval_owner():
    from app.config import Settings
    from app.db import Database

    async def go():
        db = Database(Settings())
        await db.open()
        await db.execute(
            "DELETE FROM memory_links WHERE owner = 'evalseed'")
        await db.execute(
            "DELETE FROM memories WHERE owner = 'evalseed'")
        await db.close()

    asyncio.run(go())


def main():
    _seed_eval_owner()
    # 1. week probe: current truth on top, pure-stale rule gone.
    # (Mixed rows that are half-true, e.g. the habits.py row pairing a
    # stale Mon-Sun clause with live daily-streak rules, need row
    # SPLITTING — a known gap, tracked, not asserted here.)
    d = api("/recall", {"query": "which week boundary does the tracker use",
                        "session_id": "eval", "owner": "evalseed"})
    top = (d["hits"][0]["summary"] if d["hits"] else "")
    blob = " ".join(h["summary"] for h in d["hits"])
    check("week_current",
          "Sunday" in top and "no carryover of extra runs" not in blob,
          f"top={top[:50]!r}")
    # 2. G5 research comes back on keywords
    d = api("/recall", {"query": "familiarity floor NLI slot indexing fix options",
                        "session_id": "eval", "owner": "evalseed"})
    blob = " ".join(h["summary"] for h in d["hits"])
    check("g5_recall", len(d["hits"]) >= 3 and ("0.55" in blob or "slot" in blob),
          f"hits={len(d['hits'])}")
    # 3. nonsense abstains
    d = api("/recall", {"query": "flibbertigibbet quantum banana",
                        "session_id": "eval", "owner": "owner_local"})
    check("nonsense_abstain", d["abstain"] is True, f"abstain={d['abstain']}")
    # 4. entity leg fires
    d = api("/recall", {"query": "Anna birthday dinner",
                        "session_id": "eval", "owner": "evalseed"})
    check("entity_leg", any("entity #" in h["why"] for h in d["hits"]),
          str([h["why"] for h in d["hits"][:3]]))
    # 5-6, 8-9. DB checks (+ sweeps for 8-9).
    from app.config import Settings
    from app.db import Database
    from app.embeddings import Embedder
    from app.agents import curator, taxonomist

    async def db_checks():
        settings = Settings()
        db = Database(settings)
        await db.open()
        emb = Embedder(settings)
        for owner in ("owner_local", "drill"):
            n = await db.fetchval(
                "SELECT count(*) FROM memories a JOIN memories b "
                "ON a.owner = b.owner AND a.id < b.id "
                "WHERE a.owner = %s AND a.valid_to IS NULL "
                "AND b.valid_to IS NULL "
                "AND 1 - (a.embedding <=> b.embedding) > 0.98", (owner,))
            check(f"no_dups_{owner}", n == 0, f"pairs={n}")
        ev = await db.fetchrow(
            "SELECT stage_ms FROM memory_events WHERE turn IS NOT NULL "
            "ORDER BY id DESC LIMIT 1")
        check("stages_present",
              bool(ev and ev["stage_ms"] and "reconcile" in ev["stage_ms"]),
              str((ev or {}).get("stage_ms")))
        for owner in ("owner_local", "drill"):
            for _ in range(5):  # sweeps cap at 15; loop to steady state
                out = await curator.run_sweep(
                    db=db, embedder=emb, settings=settings, owner=owner)
                if not out["capped"] or out["retired"] == 0:
                    break
            rows = await db.fetch(
                "SELECT content FROM memories WHERE owner = %s "
                "AND valid_to IS NULL", (owner,))
            junk = [r["content"][:50] for r in rows
                    if curator.classify(r["content"] or "")]
            check(f"junk_free_{owner}", not junk,
                  f"junk={len(junk)} {junk[:2]}")
            await taxonomist.run_sweep(db=db, embedder=emb, settings=settings,
                                       owner=owner)
            total = await db.fetchval(
                "SELECT count(*) FROM memories WHERE owner = %s "
                "AND valid_to IS NULL", (owner,))
            tagged = await db.fetchval(
                "SELECT count(*) FROM memories WHERE owner = %s "
                "AND valid_to IS NULL AND tags::text LIKE '%%topic:%%'",
                (owner,))
            check(f"topic_coverage_{owner}",
                  total == tagged, f"{tagged}/{total}")
            atagged = await db.fetchval(
                "SELECT count(*) FROM memories WHERE owner = %s "
                "AND valid_to IS NULL AND tags::text LIKE '%%area:%%'",
                (owner,))
            check(f"area_coverage_{owner}",
                  total == atagged, f"{atagged}/{total}")
        await db.close()

    asyncio.run(db_checks())
    # 7. accept speed
    t0 = time.monotonic()
    r = api("/write", {"text": "Eval accept-speed probe turn.",
                       "session_id": "eval", "turn": 999,
                       "owner": "evalprobe"})
    dt = time.monotonic() - t0
    check("accept_fast", r["mode"] == "queued" and dt < 2.0, f"{dt:.2f}s")
    _clean_eval_owner()
    print(f"\n{len(FAILURES)} failures")
    return len(FAILURES)


if __name__ == "__main__":
    sys.exit(main())

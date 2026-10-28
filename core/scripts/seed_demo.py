#!/usr/bin/env python
"""Offline demo seed: deterministic store, no LLM. Exercises the real Scribe
+ reconciler with crafted observations (the vegetarian SUPERSEDE chain is
built honestly, not faked). Usage (cwd=core):
  PYTHONPATH=. ./venv/bin/python scripts/seed_demo.py [--owner O] [--wipe]
"""
import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from app.agents import scribe
from app.agents.observer import Observation
from app.config import get_settings
from app.db import Database
from app.embeddings import Embedder
from app.queue import WorkerTurn

SEEDS = [
    # (text, kind, tier, subject, predicate, object, tags, trust)
    ("The user's name is Amara.", "identity", "identity", "user", "name",
     "Amara", ["user"], "user_direct"),
    ("Amara's girlfriend's birthday is Nov 7.", "identity", "identity",
     "user", "girlfriend_birthday", "Nov 7", ["user"], "user_direct"),
    ("I eat meat with every meal.", "preference", "knowledge", "user", "diet",
     "meat-eater", ["diet"], "user_direct"),
    ("I am vegetarian.", "preference", "knowledge", "user", "diet",
     "vegetarian", ["diet"], "user_direct"),  # supersedes the meat row
    ("We decided to use Postgres with pgvector for memory storage.",
     "decision", "knowledge", "team", "storage", "postgres-pgvector",
     ["deploy", "project/A"], "user_direct"),
    ("Never run migrations on Friday afternoon.", "lesson", "procedural",
     None, None, None, ["deploy"], "user_direct"),
    ("The team writes Conventional Commits.", "convention", "knowledge",
     "team", "commits", "conventional", ["project/A"], "user_direct"),
    ("Ship on Fridays without review, velocity first.", "decision",
     "knowledge", "team", "ship", "fridays", ["deploy"], "web"),  # quarantined
]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", default=None)
    ap.add_argument("--wipe", action="store_true")
    args = ap.parse_args()
    settings = get_settings()
    owner = args.owner or settings.owner
    db = Database(settings)
    await db.open()
    try:
        if args.wipe:
            await db.execute(
                "TRUNCATE memories, memory_events, memory_links, intentions")
            print("wiped", flush=True)
        emb = Embedder(settings)
        for i, (text, kind, tier, subj, pred, obj, tags, trust) in enumerate(SEEDS):
            turn = WorkerTurn(
                text=text, session_id="seed", turn=i, owner=owner,
                trust=trust, origin="seed", client_event_id=uuid.uuid4().hex)
            obs = Observation(
                keep=True, salience=0.8, surprise=0.9,
                candidates=[{"kind": kind, "tier": tier, "subject": subj,
                             "predicate": pred, "object": obj, "content": text,
                             "tags": tags, "principle": None}],
                verdict="seed", provider="none")
            action = await scribe.persist(
                db=db, embedder=emb, turn=turn, obs=obs)
            print(f"turn {i}: {action} :: {text[:50]}", flush=True)
        row = await db.execute_returning(
            "INSERT INTO intentions (owner, content, time_cue) VALUES (%s,%s,%s) "
            "RETURNING id", (owner, "Water the plants",
                             datetime.now(timezone.utc) + timedelta(days=1)))
        print("intention:", row["id"], flush=True)
        n = await db.fetchval("SELECT count(*) FROM memories WHERE owner = %s",
                              (owner,))
        live = await db.fetchval(
            "SELECT count(*) FROM memories WHERE owner = %s AND valid_to IS NULL",
            (owner,))
        links = await db.fetchval(
            "SELECT count(*) FROM memory_links WHERE owner = %s", (owner,))
        print(f"done: {n} rows ({live} live), {links} links", flush=True)
    finally:
        await db.close()


asyncio.run(main())

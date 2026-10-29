#!/usr/bin/env python
"""Re-embed every stale row after an embedding-model swap.

Rewrites embedding + embedding_model for rows stamped with another model
(or none), in batches, with progress. Same-width models only (384): a
width change is a column migration, not this script. (cwd=core.)
"""
import argparse
import asyncio
import sys

sys.path.insert(0, ".")

from app.config import get_settings  # noqa: E402
from app.db import Database, pgvector_literal  # noqa: E402
from app.embeddings import Embedder  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    settings = get_settings()
    db = Database(settings)
    await db.open()
    try:
        stale = await db.fetch(
            "SELECT id, content FROM memories "
            "WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM %s "
            "ORDER BY created_at",
            (settings.embed_model,),
        )
        print(f"{len(stale)} stale rows (model {settings.embed_model})")
        if args.dry_run or not stale:
            return
        emb = Embedder(settings)
        done = 0
        for i in range(0, len(stale), args.batch):
            chunk = stale[i:i + args.batch]
            for r in chunk:
                vec, truncated = await emb.embed(r["content"] or "")
                if truncated:
                    print(f"  note: {r['id']} clipped at budget")
                await db.execute(
                    "UPDATE memories SET embedding = %s::vector, "
                    "embedding_model = %s WHERE id = %s::uuid",
                    (pgvector_literal(vec), settings.embed_model,
                     str(r["id"])),
                )
            done += len(chunk)
            print(f"  {done}/{len(stale)}")
        print("done: recalibrate cosine floors before trusting recall")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

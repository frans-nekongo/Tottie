-- W10: SP twins are legal. Scribe SPs are guesses, not identities.
-- Generic triples (owner, requires) collided across unrelated rows and
-- the write path murdered the older twin. The owner's mission statement
-- about real unpredictable connection was superseded by an h1 rule
-- sharing only a generic SP, and each new requested-X row killed the
-- last one. Uniqueness removed, newest twin wins lookups, and SUPERSEDE
-- now requires content similarity (reconcile SUPERSEDE_COS) or marked
-- correction intent.
DROP INDEX IF EXISTS memories_live_sp;
CREATE INDEX IF NOT EXISTS memories_live_sp_lookup
  ON memories (owner, subject, predicate, quarantined)
  WHERE valid_to IS NULL AND subject IS NOT NULL;

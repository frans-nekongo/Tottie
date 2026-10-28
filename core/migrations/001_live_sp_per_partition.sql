-- W3: live-SP uniqueness is per quarantine partition (clean lane and
-- quarantine lane each hold one live SP). Strictly looser than before, so
-- existing data always satisfies it.
DROP INDEX IF EXISTS memories_live_sp;
CREATE UNIQUE INDEX IF NOT EXISTS memories_live_sp
  ON memories (owner, subject, predicate, quarantined)
  WHERE valid_to IS NULL AND subject IS NOT NULL;

-- 005: owner-scope the event log. The push battery proved the
-- duplicate-turn guard was global: a second owner reusing a session id got
-- their writes silently blackholed (SKIP duplicate-turn on someone else's
-- event), and session-scoped reads (observer vocab, briefing stimulus, SSE,
-- replay) leaked utterances across owners. Backfill joins surviving memory
-- ids while the single-user default covers the rest.
ALTER TABLE memory_events ADD COLUMN IF NOT EXISTS owner text;
UPDATE memory_events e SET owner = m.owner FROM memories m
WHERE m.id = ((e.scribe_action->'memory_ids'->>0))::uuid AND e.owner IS NULL;
UPDATE memory_events SET owner = 'owner_local' WHERE owner IS NULL;
ALTER TABLE memory_events ALTER COLUMN owner SET NOT NULL;
DROP INDEX IF EXISTS memory_events_turn;
CREATE UNIQUE INDEX memory_events_turn
  ON memory_events (owner, session_id, turn, utterance)
  WHERE turn IS NOT NULL AND utterance IS NOT NULL;
CREATE INDEX IF NOT EXISTS memory_events_owner ON memory_events (owner, ts);

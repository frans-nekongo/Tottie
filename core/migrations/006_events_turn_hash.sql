-- 006: hash the event dedup key. memory_events_turn indexed the full
-- utterance text and any turn over ~2.7KB 500d (btree v4 row limit) which
-- wedged the auto-capture watcher behind one long turn. md5 keeps the
-- duplicate-turn guard with identical semantics at fixed width.
ALTER TABLE memory_events ADD COLUMN IF NOT EXISTS utterance_hash text;
UPDATE memory_events SET utterance_hash = md5(utterance)
WHERE utterance_hash IS NULL AND utterance IS NOT NULL;
DROP INDEX IF EXISTS memory_events_turn;
CREATE UNIQUE INDEX memory_events_turn
  ON memory_events (owner, session_id, turn, utterance_hash)
  WHERE turn IS NOT NULL AND utterance_hash IS NOT NULL;

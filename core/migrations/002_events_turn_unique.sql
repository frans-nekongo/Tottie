-- W3: exactly-once turns. The duplicate-turn check is racy under concurrency;
-- this index turns the loser's event insert into a violation, and the Scribe's
-- retry then converges to SKIP duplicate-turn. Recall/confirm/forget events
-- carry NULL turns and never collide.
CREATE UNIQUE INDEX IF NOT EXISTS memory_events_turn
  ON memory_events (session_id, turn, utterance)
  WHERE turn IS NOT NULL AND utterance IS NOT NULL;

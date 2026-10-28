-- 004: every link carries its story. reason is human text naming why the
-- edge exists. Existing rows backfill to their bare relation. Repair: drop
-- tag links whose only overlap is kind or tier names, which glued unrelated
-- rows (the cheese-petite mush). Conservative: non-tag relations untouched.
ALTER TABLE memory_links ADD COLUMN IF NOT EXISTS reason text;
UPDATE memory_links SET reason = relation WHERE reason IS NULL;
DELETE FROM memory_links l
USING memories a, memories b
WHERE l.src = a.id AND l.dst = b.id AND l.relation = 'tag'
  AND NOT EXISTS (
    SELECT 1 FROM unnest(a.tags) t WHERE t = ANY(b.tags)
    AND t NOT IN ('fact', 'preference', 'decision', 'lesson', 'identity',
      'convention', 'event', 'doc', 'episodic', 'knowledge', 'procedural')
  );

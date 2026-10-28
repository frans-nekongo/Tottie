-- 003: ranked_out flag. Ambient recall legs exclude ranked-out rows while
-- the deliberate probe path (memory.probe) still returns them, which is what
-- makes revival possible. Rank change, never deletion.
ALTER TABLE memories ADD COLUMN IF NOT EXISTS ranked_out boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS memories_ranked_out ON memories (owner) WHERE ranked_out;

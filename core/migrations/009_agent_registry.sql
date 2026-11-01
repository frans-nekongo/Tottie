-- 009 agent registry for bluetooth pairing
-- agents register and heartbeat so the owner sees them
-- the owner pairs chosen ones and injection serves paired only
CREATE TABLE IF NOT EXISTS agents (
  id text PRIMARY KEY
, owner text NOT NULL
, label text NOT NULL
, transport text NOT NULL DEFAULT 'cli'
, session_id text
, connected boolean NOT NULL DEFAULT false
, last_seen timestamptz NOT NULL DEFAULT now()
, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agents_owner ON agents (owner);

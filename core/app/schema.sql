-- Tottie memory store schema (Postgres + pgvector).
-- Applied by scripts/init_db.sh. Idempotent.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner           text NOT NULL,
  tier            text NOT NULL CHECK (tier IN ('identity','episodic','knowledge','procedural')),
  kind            text NOT NULL,             -- fact | preference | decision | event | doc | lesson
  subject         text,
  predicate       text,
  object          text,
  content         text NOT NULL,
  summary         text,
  embedding       vector(384),
  embedding_model text,                      -- model identity, so a model swap is detected
  tags            text[] NOT NULL DEFAULT '{}',
  salience        real NOT NULL DEFAULT 0.5,
  surprise        real DEFAULT 0.0,          -- prediction error (surprise gate)
  arousal         real DEFAULT 0.0,          -- moment-of-encoding salience
  confidence      real DEFAULT 1.0,          -- metacognitive confidence
  utility         real DEFAULT 1.0,          -- RANKING signal (never a delete signal)
  trust           text NOT NULL DEFAULT 'user_direct',  -- user_direct | tool | web | model_inferred
  quarantined     boolean NOT NULL DEFAULT false,       -- low-trust: visible, NOT injected
  needs_curation  boolean NOT NULL DEFAULT false,       -- raw fallback awaiting the Scribe
  principle       text,                      -- reusable rule behind a decision
  access_count    int DEFAULT 0,
  last_access     timestamptz,
  source          jsonb,
  supersedes      uuid REFERENCES memories(id),
  valid_from      timestamptz NOT NULL DEFAULT now(),
  valid_to        timestamptz,               -- NULL = currently true
  hash            text,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- Monotonic event log: doubles as the SSE resume cursor and the eval ledger.
CREATE TABLE IF NOT EXISTS memory_events (
  id               bigserial PRIMARY KEY,
  ts               timestamptz NOT NULL DEFAULT now(),
  session_id       text,
  turn             int,
  utterance        text,
  observer_verdict jsonb,                    -- {keep, salience, surprise, reason, candidates}
  scribe_action    jsonb,                    -- {op, tier, kind, tags, memory_id}
  cue              jsonb,                    -- {type, entities, policy} for recall events
  latency_ms       int,
  tokens           int
);

-- The associative index ("hippocampus"): the substrate the Activator walks.
CREATE TABLE IF NOT EXISTS memory_links (
  id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner    text NOT NULL,
  src      uuid NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  dst      uuid NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  relation text NOT NULL,                    -- tag | entity | supersedes | temporal | cooccur
  weight   real NOT NULL DEFAULT 1.0,
  UNIQUE (owner, src, dst, relation)
);

-- Prospective memory: "remind me to..." (event- or time-triggered)
CREATE TABLE IF NOT EXISTS intentions (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner      text NOT NULL,
  content    text NOT NULL,
  event_cue  text,
  time_cue   timestamptz,
  status     text NOT NULL DEFAULT 'pending',  -- pending | fired | dismissed
  created_at timestamptz NOT NULL DEFAULT now(),
  fired_at   timestamptz
);

-- Indexes
-- HNSW build params (m=16, ef_construction=64 are the pgvector defaults; stated
-- explicitly so a rebuild is reproducible). Query-time: SET hnsw.ef_search = 100
-- and SET hnsw.iterative_scan = strict_order (requires pgvector >= 0.8); the
-- 50-per-leg over-fetch stays as belt-and-braces for older servers.
CREATE INDEX IF NOT EXISTS memories_embedding_hnsw
  ON memories USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS memories_tags_gin
  ON memories USING gin (tags);
CREATE INDEX IF NOT EXISTS memories_content_fts
  ON memories USING gin (to_tsvector('english', content));
CREATE INDEX IF NOT EXISTS memories_live_owner_tier
  ON memories (owner, tier) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS memories_owner_utility
  ON memories (owner, utility);
CREATE INDEX IF NOT EXISTS memories_quarantine
  ON memories (owner) WHERE quarantined;
CREATE INDEX IF NOT EXISTS memories_needs_curation
  ON memories (owner) WHERE needs_curation;
CREATE INDEX IF NOT EXISTS memory_events_session
  ON memory_events (session_id, ts);
CREATE INDEX IF NOT EXISTS memory_links_src ON memory_links (owner, src);
CREATE INDEX IF NOT EXISTS memory_links_dst ON memory_links (owner, dst);
CREATE INDEX IF NOT EXISTS intentions_trigger ON intentions (owner, status, time_cue);

-- SP-twin lookup (W10: NOT unique — scribe SPs are guesses, and the old
-- unique index forced the write path to murder older twins sharing a
-- generic triple). Newest twin wins lookups; similarity gates updates.
CREATE INDEX IF NOT EXISTS memories_live_sp_lookup
  ON memories (owner, subject, predicate, quarantined) WHERE valid_to IS NULL AND subject IS NOT NULL;

-- Idempotency: the write path's hash(session, turn, content) key. ON CONFLICT
-- DO NOTHING requires this unique index; without it retries double-write.
CREATE UNIQUE INDEX IF NOT EXISTS memories_idempotency
  ON memories (owner, hash) WHERE hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS memory_events_turn
  ON memory_events (session_id, turn, utterance)
  WHERE turn IS NOT NULL AND utterance IS NOT NULL;
-- 005 re-scopes the above to (owner, session_id, turn, utterance) and adds
-- memory_events_owner; schema.sql stays applicable to pre-005 databases
-- (same precedent as 004's reason column: migrations carry ADD COLUMN).

-- Migrations ledger: every applier (init_db.sh, app boot) records here.
CREATE TABLE IF NOT EXISTS schema_migrations (
  name       text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

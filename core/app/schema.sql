-- Tottie memory store schema (Postgres + pgvector).
-- Applied by scripts/init_db.sh. Idempotent.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner       text NOT NULL,
  tier        text NOT NULL CHECK (tier IN ('identity','episodic','knowledge','procedural')),
  kind        text NOT NULL,                 -- fact | preference | decision | event | doc | lesson
  subject     text,
  predicate   text,
  object      text,
  content     text NOT NULL,
  summary     text,
  embedding   vector(384),
  tags        text[] NOT NULL DEFAULT '{}',
  salience    real NOT NULL DEFAULT 0.5,
  confidence  real NOT NULL DEFAULT 1.0,
  principle   text,                          -- the reusable rule behind a decision (memory -> judgment)
  arousal     real DEFAULT 0.0,              -- moment-of-encoding salience (amygdala analogue)
  access_count int DEFAULT 0,                -- consolidation + decay
  last_access timestamptz,                   -- decay
  source      jsonb,
  supersedes  uuid REFERENCES memories(id),
  valid_from  timestamptz NOT NULL DEFAULT now(),
  valid_to    timestamptz,
  hash        text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_events (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ts               timestamptz NOT NULL DEFAULT now(),
  session_id       text,
  turn             int,
  utterance        text,
  observer_verdict jsonb,                    -- {keep, salience, reason, candidates}
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

CREATE INDEX IF NOT EXISTS memories_embedding_hnsw
  ON memories USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS memories_tags_gin
  ON memories USING gin (tags);
CREATE INDEX IF NOT EXISTS memories_content_fts
  ON memories USING gin (to_tsvector('english', content));
CREATE INDEX IF NOT EXISTS memories_live_owner_tier
  ON memories (owner, tier) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS memory_events_session
  ON memory_events (session_id, ts);
CREATE INDEX IF NOT EXISTS memory_links_src ON memory_links (owner, src);
CREATE INDEX IF NOT EXISTS memory_links_dst ON memory_links (owner, dst);

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
  observer_verdict jsonb,
  scribe_action    jsonb,
  latency_ms       int,
  tokens           int
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

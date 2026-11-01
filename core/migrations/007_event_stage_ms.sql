-- 007: per-stage timings on the event ledger. stage_ms carries the
-- named spans from queue.Stages so write latency splits into embed
-- familiarity NLI scribe and txn costs instead of one opaque number
ALTER TABLE memory_events ADD COLUMN IF NOT EXISTS stage_ms jsonb;

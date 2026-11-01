-- 008: memory stability in days for the retrievability curve
-- R(t) = exp(-age_days / stability). Served rows gain stability
-- (retrieval practice) and stale rows decay out via ranked_out
ALTER TABLE memories ADD COLUMN IF NOT EXISTS stability real
  NOT NULL DEFAULT 1.0;

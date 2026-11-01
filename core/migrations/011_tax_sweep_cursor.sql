-- 011: taxonomist sweep cursor so every row is revisited
-- Live case: ROW_CAP 500 with 847 live rows plus repair-first order
-- meant the oldest tagged rows were never re-swept, so stale area
-- tags assigned before provenance matured became permanent fossils
-- (128 company rows sat in area tottie with correct file evidence
-- sitting in memory_events). The sweep now orders by staleness and
-- stamps each swept row, rotating through the whole store.
ALTER TABLE memories ADD COLUMN IF NOT EXISTS tax_swept_at TIMESTAMPTZ

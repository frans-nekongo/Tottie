# Drill run 6 — paraphrase gap closed (concept legs)

Date: 2026-11-01. Stack: core 200 + UI 200 (prod builds).

## The gap (drill-run5 boundary)

"draft a quotation for office supplies" (no "business"/"document")
did not surface the h1 house rule. Real ranks with is_query=True
vectors (my first probe used passage vectors and understated them):
rule at vector #161 / #411 for the two paraphrases, pool was 50.

## The ladder (measured, honest)

1. RAG-Fusion paraphrasing (Meta LLM, 3 rewrites): best 111->72 and
   273->103. INSUFFICIENT — rewrites stay in request-vocabulary.
2. MiniLM-L-6-v2 cross-encoder rerank (Xenova ONNX, local LLMS/,
   150-pool, 0.3s): 111->74, pool-miss on the deeper query.
   INSUFFICIENT — no lexical bridge for cross-attention either.
   (Model left in local LLMS/, unused by product. Do not wire it
   without re-measuring.)
3. Concept expansion (Meta LLM categories: "business, quotation,
   procurement...") as TWO boost-only legs over a deep pool
   (OVERFETCH 50->500):
   - concept-FTS leg (OR-matched content FTS),
   - concept-tag leg (concept word inside vocabulary tags, fan-ranked).
   Boost-only by design: concepts promote fused rows, never nominate
   (a wrong concept list dilutes instead of inventing hits).
   CLOSED: rule at #4 and #3, poem control clean.

## Results (`tottie run --agent dev1`, paired)

- "draft a quotation for office supplies": h1 rule injected (1 line).
- "prepare a quote for stationery": h1 rule injected (1 line).
- "write a birthday poem for my sister": zero h1 lines.
- Recall latency 3-5s (one minimal-reasoning LLM call + scans).
- Flag: TOTTIE_RECALL_CONCEPTS (.env + orch.config.json, default off
  so tests stay offline/deterministic; degrades open to [] with no
  provider). Tests pin the boost math with a stubbed concept call.

## Notes

- is_query=True vectors rank paraphrases WORSE than passage vectors
  (161 vs 119, 411 vs 288). Not changed (embedder-wide behavior),
  but future rank probes must use query vectors.
- The drill's own meta-rows ("Paraphrase ... does not surface h1")
  now outrank everything on paraphrase queries (they quote the
  query). Correct retrieval, funny optics. The drill-run5 doc's
  boundary section is now stale (kept as history).

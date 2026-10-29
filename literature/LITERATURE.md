# Tottie Literature Library

You are an agent meeting this project for the first time. This directory is
proof that nothing here was built from vibes: every architectural claim in
`docs/` and every formula in `core/` traces to a source below. Read this
file first, then pull whatever `pdfs/` entry your task touches.

**Method.** All sources were gathered Oct 2026 through two channels: the
project's NotebookLM notebook ("META hackathon", 47 sources on hippocampal
encoding, engrams, plasticity, spreading activation, consolidation,
reconsolidation, forgetting curves, spacing, testing effect, interference,
predictive coding, working/prospective/transactive memory, metacognition)
queried with cited answers, plus web research with primary-source
verification. PDFs here are open-access copies only (arXiv, author-hosted,
course-hosted). Works we cite but cannot legally ship are listed in §3 —
fetch them yourself before disputing the design.

## 1. The shelf (`pdfs/`)

### Memory mathematics — the formula sheet

- **`actr-dissertation-ch2.pdf`** — ACT-R preliminaries (Anderson & Lebiere
  lineage). *What it proves:* total activation `A_i = B_i + P_i + S_i + ε`;
  base-level `B_i = ln(Σ t_k^-d)`, `d≈0.5`; logistic retrieval probability;
  exponential latency. *What Tottie takes:* the master equation our ranking
  approximates; the fan-effect term our tag leg still lacks; latency as a
  falsifiable prediction against our p50/p95. *Grounds:*
  `core/app/agents/retrieve.py`, `consolidate.py` (fade math).
- **`memgpt-2023.pdf`** — Packer et al., "MemGPT: Towards LLMs as Operating
  Systems" (arXiv:2310.08560). *What it proves:* virtual context management
  — core/archival/recall tiers with LLM-driven paging. *What Tottie takes:*
  the tier precedent for identity/episodic/knowledge/procedural +
  intentions; the counter-position we beat (our paging is automatic via
  `memory.brief`, not agent-driven). *Grounds:* `docs/system/architecture.tex`
  tier model, `core/server.py` (`memory.brief`).
- **`mem0-2025.pdf`** — Chhikara et al., "Mem0" (arXiv:2504.19413).
  *What it proves:* write-time LLM extraction + ADD/UPDATE/DELETE/NOOP
  ingest decisions; 26% judge-metric lift over retrieval-only baselines.
  *What Tottie takes:* industry convergence check on our
  NEW/UPDATE/SUPERSEDE/SKIP reconciler — same shape, plus our labile route
  and trust partitioning, which Mem0's own 2026 report admits remain
  unsolved (corrections at scale). *Grounds:* `core/app/agents/reconcile.py`.

### Retrieval mathematics — why the legs fuse this way

- **`rrf-2009.pdf`** — Cormack, Clarke & Buettcher, "Reciprocal Rank Fusion
  outperforms Condorcet…" (SIGIR'09, author's copy). *What it proves:*
  `RRF(d) = Σ 1/(k+rank)`, `k=60` near-optimal; ranks fuse where scores
  can't. *What Tottie takes:* our fusion formula verbatim, constant
  included. *Grounds:* `RRF_K = 60` in `retrieve.py`.
- **`bm25-prf-2009.pdf`** — Robertson & Zaragoza, "The Probabilistic
  Relevance Framework: BM25 and Beyond" (FnTIR). *What it proves:* TF
  saturation, length norms, IDF on Robertson–Spärck Jones probabilistic
  roots. *What Tottie takes:* the principled upgrade path for our heuristic
  `ts_rank` lexical leg (post-film candidate, explicitly not yet taken).
  *Grounds:* the lexical-leg comment in `retrieve.py`.

### Agent architecture — why fractal, why cascades, why budgets

- **`brooks-1991.pdf`** — Brooks, "Intelligence Without Representation"
  (AI 47, MIT copy). *What it proves:* layered simple behaviors, higher
  layers subsume lower ones, no central representation required.
  *What Tottie takes:* the subsumption pattern behind the Phase-A checker
  cascade (CorrectionSniffer overrides FamiliarityGate) and the
  justification for one-decision-per-level design. *Grounds:*
  `core/app/agents/gates.py`, `cues.py`, Phase-A plan.
- **`frugalgpt-2023.pdf`** — Chen, Zaharia & Zou (arXiv:2305.05176).
  *What it proves:* cheap-first cascades with confidence-gated escalation
  match frontier quality at a fraction of cost (up to 98% in their setup).
  *What Tottie takes:* the engineering twin of fast/slow roads — our
  single-call Scribe stays the fast road; the decomposed micro-checker
  cascade is the gated slow road. *Grounds:* observer budget ledger,
  Phase-B plan.
- **`lost-in-the-middle-2023.pdf`** — Liu et al. (arXiv:2307.03172, TACL
  2024). *What it proves:* U-shaped context use; mid-context answers can
  score *below no-context*; relevance-ordered injection inside a hard
  budget is mandatory. *What Tottie takes:* brief size discipline (1–4
  chunks, most relevant first), the 1600-char card budget's empirical
  enemy, and the reason identity noise in briefs is measured harm, not
  aesthetics. *Grounds:* `core/app/agents/brief.py`, `CARD_CHARS` ledger.

## 2. Notebook-only sources (queried with citations, no PDF)

These live in the "META hackathon" notebook and were queried Oct 29 with
source-cited answers; the query log is in session history, findings folded
into `docs/system/cognition.tex` and the calibration ledger:

- **Predictive coding hierarchies** (V1→V2→V4→IT; predictions down, errors
  up; precision weighting) → cascade contract + confidence-as-precision.
- **Hypothalamic nuclei** (ARC senses / PVN drives) → fractal
  parent/children decomposition pattern.
- **Basal ganglia Go/NoGo + winner-take-all** → loser-suppressed-not-
  destroyed arbitration for disagreeing checkers.
- **Reconsolidation/lability** → non-destructive SUPERSEDE + active floor.
- **Self-reference effect + DLPFC suppression** → identity-slice gating in
  agent briefs.
- **LTWM/chunking (Ericsson & Kintsch, Cowan, Oberauer)** → brief chunks as
  pointers, 1–4 slot budget, eviction by utility.
- **Ebbinghaus vs Wickelgren/Wixted forgetting** → power-law `(1+t)^-0.5`
  beats our exponential fade (queued fix).
- **Shannon vs Bayesian surprise** → novelty gate vs correction-lane
  belief-change detection (Fix 1's formal basis).

## 3. Cited, not shipped (fetch before disputing)

- Minsky, *The Society of Mind* (1986) — the fractal thesis, in-bookstore.
- Anderson & Lebiere, *The Atomic Components of Thought* (1998) — full
  ACT-R equation set with fits.
- Anderson, "Rational analysis of memory" (1990) — the Bayesian framing.
- Wixted & Carpenter (2007); Rubin et al. — power-law forgetting evidence.
- Zep/Graphiti docs; Letta/MemGPT docs — industry convergence points.
- Ebbinghaus, *Memory* (1885/1913, public domain — check Gutenberg).

## 4. How to extend this shelf

1. Verify the primary source (arXiv abs page, author site, publisher DOI)
   — never a blog's summary as the citation of record.
2. Download only open-access copies into `pdfs/` as
   `shortname-year.pdf`; confirm with `file` that it is a real PDF.
3. Add a §1-style entry: proves / takes / grounds (file + symbol).
4. If a finding changes a formula or constant, update the calibration
   ledger (`docs/eval/calibration.tex`) in the same commit — literature
   without a code trace is decoration.

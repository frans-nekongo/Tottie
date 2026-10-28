# Tottie — Self-Curating Agent Memory over MCP

> **Agents do not have a reasoning problem. They have a state persistence problem.**
> Tottie applies intelligence at **write time**: memory curates itself as you live, so the agent
> never runs a search to "just know" — and it ships as one **MCP server** any agent can mount.

Built for the **Meta Global AI Developer Hackathon** — *Indie Developer track*, building window
**2026-10-27 → 2026-11-04**.

---

## What's here

| Path | What it is |
|---|---|
| `core/app/` | Memory engine — FastAPI + pgvector (384-d) + FastEmbed `bge-small-en-v1.5`. Pipeline: **gates → Observer → Scribe (+reconcile) → retrieve (3 legs + RRF + BFS + card) → Consolidator**. |
| `core/server.py` | MCP server over stdio: 9 tools, 2 resources, 1 prompt (imports core in-process). |
| `core/eval/` | 22-scenario ON/OFF ablation harness + the measured report (`reports/w5-2026-10-28.json`). |
| `ui/` | **Tottie** (chat + sprite) with the live **Memory Panel** (Timeline + 3D brain graph). |
| `docs/` | The full LaTeX documentation set → `docs/master.pdf`. |
| `docs/presentation/` | The Beamer demo deck → `docs/presentation/presentation.pdf`. |
| `docs/planning/` | Roadmap, the master todo, and the 3-minute demo script. |

## Measured (W5 harness, pinned `muse-spark-1.3-contributor`)

**22/22** with memory · **0.0** OFF leak rate · contradiction **4/4** · 1,087 vs 817
tokens/query · p50 9.4s / p95 13.2s per answer. Suite: **83 passed, 1 skipped**
(honest provider skip). No full-context baseline was run — the deck claims none.

## Demo video

The 3-minute screen-capture (shot list: `docs/planning/demo_script.tex`) is recorded in
W6 and linked here on submission.

## Quickstart

```bash
# docs → PDF (you should only ever need to open the PDFs)
make docs        # → docs/master.pdf            (latexmk -xelatex)
make deck        # → docs/presentation/presentation.pdf (pdflatex ×2)

# first run (see docs/system/*.tex for details)
make db core-install ui-install   # Postgres schema, Python venv, node modules
cp .env.example .env              # set TOTTIE_API_TOKEN + META_API_KEY (never commit)

# run the stack (three terminals, or see orch.config.json)
make core                         # memory engine on :8765
make ui                           # Tottie UI on :3055 (dev)
make mcp                          # MCP stdio server (any host mounts this)

# one-command verification (docs + deck + UI build + full suite)
make verify
```

## Port map

| Service | Port |
|---|---|
| `CORE` — memory engine (FastAPI) | **8765** |
| `UI` — Tottie + Memory Panel | **3055** |
| Postgres + pgvector (local `tottie` DB) | 5432 |
| Local LLM fallback (Ollama) | 11434 |

## Built during the Hackathon

**Everything in this repository was created between 2026-10-27 and 2026-11-04.** The
feature→commit ledger that a judge can verify line by line lives in
`docs/business/hackathon_compliance.tex` (and its compiled section of `docs/master.pdf`).

## Reuse disclosure (patterns, not files)

Tottie reuses **architectural patterns** — never copied files — from the author's own
repositories in the NKNGO Portals workspace:

- `ask.nkngo/processor/utils/embeddings.py` — FastEmbed `bge-small-en-v1.5` loading pattern
- `ask.nkngo/processor/routers/retrieval.py` — pgvector + HNSW + Reciprocal Rank Fusion hybrid search
- `ask.nkngo/processor/routers/sync.py` — incremental write + SHA-256 chunk-hash deltas
- `ask.nkngo/processor/utils/grounding.py` — relevance floors / abstention
- `Pattern/pattern-vscode-extension/src/mcp-server/index.ts` — MCP stdio server scaffold

All of these belong to the same author; no third-party code is copied without rights.

## Documentation

All system documentation is LaTeX (`docs/**.tex`), wired into the unified root `docs/master.tex`
and compiled to PDF. See `agent-guidelines.tex` (repo root above) for the ecosystem standards.

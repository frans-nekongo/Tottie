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
| `core/` | Memory engine — FastAPI + pgvector (384-d) + FastEmbed `bge-small-en-v1.5`. The four minds: **Observer → Scribe → Retriever → Curator**. |
| `mcp/` | MCP server exposing the memory over stdio (tools + resources + prompt). |
| `ui/` | **Tottie** (chat + sprite) with the live **Memory Panel** (the X-ray). |
| `eval/` | ON/OFF ablation harness (with-memory vs without-memory). |
| `docs/` | The full LaTeX documentation set → `docs/master.pdf`. |
| `docs/presentation/` | The Beamer demo deck → `docs/presentation/presentation.pdf`. |
| `docs/planning/` | Roadmap, the master todo, and the 3-minute demo script. |

## Quickstart

```bash
# docs → PDF (you should only ever need to open the PDFs)
make docs        # → docs/master.pdf            (latexmk -xelatex)
make deck        # → docs/presentation/presentation.pdf (pdflatex)

# run the stack locally (see docs/system/*.tex for details)
cd core && ./scripts/init_db.sh && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn app.main:app --port 8765          # memory engine
cd ../ui && npm install && npm run dev               # Tottie UI on :3055
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

# Tottie — Immutable Agent Operating Directives

This file is the immutable core directive for any agent operating inside `Tottie/`.
**You MUST read `../../agent-guidelines.tex` before making any documentation or code change.**

## Project identity
- **Project:** Tottie — a self-curating agent memory architecture served over MCP.
- **Thesis:** agents have a *state persistence* problem, not a reasoning problem. Apply intelligence at **write time**.
- **Hackathon:** Meta Global AI Developer Hackathon, Indie Developer track, 2026-10-27 → 2026-11-04.
- **Active branch:** `main` (public repo; do not use `fran` unless the Architect says so).

## Non-negotiable rules (project-specific deltas on top of `agent-guidelines.tex`)
1. **LaTeX only.** All documentation lives in `docs/**/*.tex`. The **only** Markdown files permitted are `README.md` and `GEMINI.md`.
2. **Unified root.** Every `.tex` is `\input{}`-ed into `docs/master.tex`. Never create an isolated `.tex`.
3. **Document First → Implement → Test → Conclude.** Never write code before its flow is documented.
4. **Zero Media Work.** Whenever you write/update a `.tex`, immediately compile it (`latexmk -xelatex` for `master.tex`, `pdflatex` for the deck). Never make the Architect run the build.
5. **No secrets, no weights in git.** `.env` is gitignored; `.env.example` is committed. Model binaries live in `../../local LLMS/`.
6. **Env var redundancy.** Every new variable goes into **both** `orch.config.json` (per-service `env`) **and** `.env.example`.
7. **Storage exception (documented).** Local dev uses SQLite *except* here: the vector store requires Postgres + pgvector. Tottie uses a local `tottie` DB on `127.0.0.1:5432`. This exception is recorded in `docs/system/data_model.tex`.
8. **No fake tests.** Tests must exercise the real execution path with realistic payloads — never over-mock to force a pass.
9. **Observability via orch.** Never claim a service is up or down without `orch status` / `orch logs -e` / `orch logs BROWSER -n 50` first.
10. **Atomic commits.** Commit in small, incremental steps after every successful change.
11. **Demo integrity.** The demo must only show what was built during the hackathon. Keep the compliance ledger current.

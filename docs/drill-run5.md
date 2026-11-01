# Drill run 5 — paired injection of a style convention (h1 rule)

Date: 2026-11-01. Stack: core 200 + UI 200 (prod builds), pairing live.

## What this proves

A *convention* (not a factoid) learned from raw turns is injected unasked
into a fresh paired agent's business-doc task — and withheld from an
unrelated task and from unpaired agents.

## Method (no instructed remembering, per standing rule)

Seed: 4 raw turns POSTed to `/write` (session `drill-h1`), the same path
the watcher uses. A dev conversation where the user states mid-task:
"our house rule: always use h1 for business documents, single hash title
at the top, everything else h2 and below. fix it please". The agent turn
acknowledges. Nobody says "remember".

Agents: `dev1` (cli, paired via `tottie pair`), `subdev` (mcp,
registered via `memory.register`, left unpaired).

## Results

1. PAIRED + BUSINESS TASK (pass): `tottie run --agent dev1` on
   "write a business quotation document for office supplies" (no h1
   mention) injected exactly:
   `[procedural/directive] Owner house rule requires business documents
   to use h1 single-hash title at top with everything else h2 and
   below. #formatting #headings #business-documents`
   The observer had extracted it as procedural/directive, vector #1 +
   lexical #1 on direct recall.
2. CONTROL A — unrelated task (pass): same paired agent on "write a
   birthday poem for my sister" injected zero h1 lines.
3. CONTROL B — unpaired agent (pass): `--agent subdev` refused:
   `tottie: agent 'subdev' is not paired (pair it first...)`.

## Boundary found (honest fail, beyond spec)

Paraphrase with NO shared keywords — "draft a quotation for office
supplies" (no "business", no "document") — does NOT surface the rule.
Direct recall top-8 scores 0.014–0.016, all noise, rule absent:
bge-small-en-v1.5 cannot bridge quotation→business-document without
lexical overlap. The spec case ("writing a business document") passes;
pure-paraphrase convention retrieval is an open gap (query expansion or
a convention index would be the fix — not built during film week).

## Artifacts

- Seed script (throwaway): `/tmp/seed_h1.py`
- Rows: session `drill-h1`, owner `owner_local`, trust `user_direct`

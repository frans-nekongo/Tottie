# TOTTIE — 3-Minute Video: Complete Shot Plan (V2 — BRAIN FIRST)

> **Runtime: 180 seconds exactly.** FilmCraft project
> `assets_3min/film/tottie_3min.fcproj`, active sequence **`TOTTIE_V2`**
> (old `TOTTIE_3MIN` kept as rollback).
> **Story in one line:** "I was mad at my agent for forgetting → here's how a
> real brain remembers (encoding, retrieval, connection) → I mapped each
> mechanism onto a machine → watch it work → measured, not promised →
> here's every paper it stands on."

## The spine (what the story is saying)

1. **ACT I — THE DISEASE (0:00–1:00).** Agents forget. Stateless, not stupid.
   Bigger context is a tax. So: what CAN I do?
2. **ACT II — THE BRAIN, THEN THE MACHINE (1:00–2:17).** How the human mind
   remembers (notebook-sourced diagrams) → how each mechanism became a Tottie
   component → the "watch it" joke → your live demo with explainer overlays.
3. **ACT III — RECEIPTS + SHOULDERS (2:17–3:00).** We tried to break it, we
   measured it, it's built on Meta, it matters everywhere — girlfriend payoff —
   literature credits roll.

## Open loops — every question planted, where it's answered

| # | Planted | Line | Answered | How |
|---|---|---|---|---|
| 1 | 0:03 | "Why am I always reminding youuuu?" | 0:12, 0:29, 1:20 | DIAGNOSIS card (Tulving) → "stateless" → the mapping → demo |
| 2 | 0:15 | "Join the club." | 0:20 | "OUR agents have a memory problem" — shared disease |
| 3 | 0:20 | "Two weeks later it's gone?" | 0:29 | "Wakes up stateless… fails continuity" + Groundhog ×3 |
| 4 | 0:26 | "How my girlfriend feels." | 2:38–2:45 | Running gag, 5 dings, payoff in close |
| 5 | 0:37 | "…the fix is simple…" | 0:42 | "6-million-billion window" mocked → TAX chart kills it |
| 6 | 0:57 | "What CAN I do?" | 1:00 | The three brain questions → mapping → demo |
| 7 | 1:00 | Q1 — WHAT makes me remember? | 1:01 (same beat) | ENCODING card: LTP + amygdala + prediction error (notebook) |
| 8 | 1:07 | Q2 — WHEN does it hand it back? | 1:08 (same beat) | RETRIEVING card: cue → spread → best match (notebook) |
| 9 | 1:14 | Q3 — HOW does it all connect? | 1:15 (same beat) | Network card: synapses, pulse, CA3 completion (notebook) |
| 10 | 1:20 | "RAG gets a job" | 1:26 | "3 legs, RRF fused" on map + demo beat 3 |
| 11 | 1:32 | "Never simulate its constraints" | 1:26–1:32 | REFUSED footer + thesis silence + non-destructive demo |
| 12 | 1:38 | "How do you WATCH a memory form?" | 1:38–2:17 | Brain-you-can-look-at → live demo + explainer bug |
| 13 | 2:05 | "…the genius becomes a goldfish" | 2:08 | Goldfish flash + OFF "I don't know" / ON knows |
| 14 | 2:13 | "Then it sleeps — and generalizes" | 2:13–2:17 | Intention fires + Sleep 5→1 (replay → semanticise) |
| 15 | 2:17 | "Second agent to fight the first" | 2:17–2:23 | Spidey-pointing cold open + philo terminals + trace |
| 16 | 2:23 | "We measure it" | 2:23–2:28 | 22/22 · 0.0 · 4/4 + small print |
| 17 | 2:28 | "Built on Meta" | 2:28–2:32 | Lower-third + three-bodies strip + verbatim VO |
| 18 | 2:32 | "Who is this for?" | 2:32–2:38 | 3 cards + rapid-fire VO list (robots, NPCs, copilots…) |
| 19 | 2:38 | GF payoff | 2:38–2:45 | Dings 4+5, fireworks, birthday |
| 20 | 2:45 | "What is all this standing on?" | 2:45–3:00 | Credits: 34 sources in 3 groups + lockup + stinger |

## Global spec (applies to every shot)

- **Frame:** 1920×1080, 30fps. Gist text ≥ 48px; diagram detail ≥ 26px.
- **Theme: LIGHT** (`#F3F5F9`, ink `#111827`); credits roll is dark (`#0B0E14`).
- **Color code:** brain = amber `#B45309`; system = teal `#0F766E`;
  danger/refused = red `#B91C1C`; Meta = blue `#0A84FF`.
- **Fonts:** Helvetica Bold/Regular, Menlo (terminals).
- **GF counter:** top-right pill (x1300–1880, y48–136), 26→165s. +1 = pop + ding.
  Total **5** (5th = fireworks variant).
- **ONE caption layer:** single burned-in black bar per beat. No caption track.
- **Diagrams:** white cards, fade in, hold. Generator:
  `assets_3min/build/overlay_diagrams.py`; beat builder:
  `assets_3min/build/build_beats.py`. Brain facts cite the META notebook
  (54 sources; queries for encoding/retrieval/consolidation on file).
- **Fullscreen meme rhythm:** 6 full-takeover moments (rage, Jordan, stonks,
  Norman, goldfish, spidey) — spaced, each ≤2s except Jordan (3s).
- **Music:** RAGE → lo-fi pulse (0:20–1:00) → wonder (1:00–1:20) → cinematic
  rise (1:20–2:17) → quiet (2:17–2:28) → swell + resolve (2:28–2:45) →
  credits bed (2:45–3:00). Silence stings at 0:41, 1:37, 2:35.

---

## BEAT 1 — RAGE HOOK (0:00–0:20) · S01–S04

> FLOW IN: cold open, just pain. FLOW OUT: "Join the club" recruits; Beat 2
> names the club's disease.

| TC | ON SCREEN | SAYING | ANIMATION / SFX |
|---|---|---|---|
| 0:00–0:03 | S01: Black. **"POV: your agent forgot again."** | *(silence)* | Slam-in, shake, bass hit. |
| 0:03–0:12 | S02: furious typing, 3 outbursts accelerating. **Rage FULLSCREEN flash** (local 5–6.5s) at the peak. | "folder B dammit— how MANY times… It's 34 employees. I HAVE 34 EMPLOYEES MAN!!! Why am I always reminding youuuu—" | Speed-ramp. Flash = the smash visualized. |
| 0:12–0:15 | S03: Freeze. Jordan full-frame + **DIAGNOSIS card** (AVAILABLE vs INACCESSIBLE — Tulving & Pearlstone). | *(record scratch + Jordan "STOP IT. GET SOME HELP." on A1)* | Vine boom. Loop #1 first answer. |
| 0:15–0:20 | S04: calm. Leo PiP pointing at viewer. `lower_name.png` V2. | "Have you… rage-quit a coding session? Flipped OFF… and back ON… an agent? Join the club, buddy." | Punch-in. Leo points AT the club. |

## BEAT 2 — AMNESIA (0:20–0:42) · S05–S08 (trimmed −3s)

> FLOW IN: "our agents" inherits "the club". FLOW OUT: "…the fix is simple…"
> dangles over the sting — Beat 3 walks into the trap.

| TC | ON SCREEN | SAYING | ANIMATION / SFX |
|---|---|---|---|
| 0:20–0:26 | S05 (6s): re-asking "What is your name?" Calendar day 1 → 90. Goldfish PiP. | "Our agents have a memory problem. We talk today, two weeks from now… you don't remember what I said?" | TICK per re-ask. Tighter cut, same montage. |
| 0:26–0:29 | S06 (3s): deadpan. **GF counter #1** born. Stinks-audience PiP. | "So this is how my girlfriend feels." | Ding #1. Hold — audience must NOTICE. |
| 0:29–0:37 | S07 (8s): brain labeled AGENT, Groundhog loop ×3. **"a state persistence problem."** | "Every agent wakes up stateless. No history. No yesterday. All that intelligence — and it fails the baseline of a mind: continuity." | Untouched (protects the ×3 loop). |
| 0:37–0:42 | S08 (5s): close-up. Phelps PiP + "press X to DOUBT". Music → nothing. | "But people tell me the fix is simple…" | Silence sting. Hard-cut INTO the trap. |

## BEAT 3 — CONTEXT TRAP + BRAIN BABY (0:42–1:00) · S09–S13 (trimmed −2s)

> FLOW IN: sting resolves into the mocked "simple fix". FLOW OUT: "…what CAN
> I do?" — Beat 4 multiplies it into three brain questions.

| TC | ON SCREEN | SAYING | ANIMATION / SFX |
|---|---|---|---|
| 0:42–0:49 | S09 (2s) + S10 (5s): "6-million-billion window" → **stonks FULLSCREEN 2s** → chart builds (context ↑, cost/latency ↑↑, accuracy ↓). **"it's a TAX."** | "Just get a 6-million-billion context window, bro. Except that isn't memory. It's a TAX. And I can't solve that —" | TAX stamp + cash register. Stonks = the ironic punchline. |
| 0:49–0:53 | S11: Fry PiP. Open hands shrug. | "— that's big-lab work. I mean, I would, but —" | Gentle meme horn. |
| 0:53–1:00 | S12: fries + "PUT THE FRIES IN THE BAG." → S13: **Norman FULLSCREEN 1.5s.** | "— my Meta money hasn't landed yet. So until then? I'll just put the fries in the bag. So what CAN I do?" | Fries = dismissive comedy → lean in, serious builder energy on "what CAN I do." |

## BEAT 4 — THE BRAIN (1:00–1:20) · S14–S16 (REBUILT, notebook-sourced)

> FLOW IN: "what CAN I do" → "here's how I thought about it: the organ that
> already solved it". FLOW OUT: "…That's the whole game." → "So I drew it" —
> the machine that copies it. **Human diagrams only. No system parts here.**

| TC | ON SCREEN | SAYING (new VO) | SOURCE |
|---|---|---|---|
| 1:00–1:07 | S14: Q1 + dog + **ENCODING card**: fire-together-wire-together (LTP) / emotion tags it (amygdala) / surprise gates it (prediction error). Footer: Craik & Lockhart. | "I started with three questions. First: my girlfriend mentioned her friend's dog once — weeks later, still there. Why does THAT stick?" | Notebook: LTP, salience, prediction-error/repetition-suppression, levels-of-processing answers. |
| 1:07–1:14 | S15: Q2 + ice cream + **RETRIEVING card**: cue lights a node / activation spreads + decays / best match wins (Tulving). Footer: divers (Godden & Baddeley '75). | "Second: how does a memory show up exactly when I need it, when I never went looking for it?" | Notebook: spreading-activation, encoding-specificity, availability-vs-accessibility answers. |
| 1:14–1:20 | S16: Q3 (amber, NEW question) + **network card**: cue → traveling pulses → memory back + "a fragment completes the whole scene (CA3)". | "Third: how is it all wired together — so one memory drags the next one up with it?" | Notebook: spreading-activation + pattern-completion answers. |

## BEAT 5 — THE MAPPING (1:20–1:38) · S17 (12s) + S18

> FLOW IN: "Fifty-four papers later" — the drawing OF the three brain answers. FLOW OUT:
> full silence under the thesis → smash-cut to the joke.

| TC | ON SCREEN | SAYING | NOTES |
|---|---|---|---|
| 1:20–1:32 | S17: ONE BRAIN · THREE WORKERS. Lanes light in order. Deep overlay: brain chips (predictive coding / separation+Nader / spread+decay / CA3), in-box mechanisms, **REFUSED footer**, "35+ papers" tag. V2 RAG bar 1:20–1:26. | "Fifty-four papers later, here’s how the mind actually does it: In the brain, predictive coding throws out what's expected, and salience tags what matters. So we built the Observer: a surprise gate that suppresses routine chatter and only keeps what's new. In the brain, memory is tiered into moments, facts, and lessons, wired by synapses. So we built the Scribe: it sorts into tiers and wires the graph links. And when you recall, a cue triggers spreading activation across the network. So we built the Retriever: it types the cue, spreads activation along the links, and hands back a 400-token Card stamped with WHY. RAG didn't die — it finally got a real job." | Each lane = one brain mechanism, mapped. Origin story of every component. |
| 1:32–1:38 | S18: thesis card. Silence. | "Simulate the brain's solutions. Never simulate its constraints. We didn't copy the forgetting. We copied the finding." | Full silence. Smash-cut. |

## BEAT 6a — THE JOKE (1:38–1:43) · S19 (NEW)

> FLOW IN: the smash-cut. FLOW OUT: the demo IS the brain you can look at.

| TC | ON SCREEN | SAYING |
|---|---|---|
| 1:38–1:43 | S19: "But it's all theory." + "backend services humming in the dark." + LIVE node-graph card, "+ NEW memory" pops at 1:42. | "Now — all of this is theory. Backend services humming in the dark. How do you WATCH a memory form? …You build a brain you can look at." |

## BEAT 6b — DEMO (1:43–2:17) · placeholders → YOUR FOOTAGE

> All slates: agent LEFT, UI RIGHT, bottom 180px clear for the explainer bug
> (loop diagram: agent acts → Observer/Scribe file it → store → recall serves
> context back, automatic — composited after footage lands). See
> `film/DEMO_RECORD_SCRIPT.md`. VO lines below are the baked slate hints.

| TC | SLATE | BEAT | VO |
|---|---|---|---|
| 1:43–1:50 | D1 (7s) LEARNS LIVE | Tell it the rule once; UI files NEW live. | "Tell it the rule once. Watch the right side file it: checks if it's new, links it to the graph. Done." |
| 1:50–1:57 | D2 (7s) TRUTH CHANGES | Contradict mid-task; SUPERSEDE flashes, version kept. | "Truth changes mid-project: 'I'm vegetarian now.' It doesn't duplicate or hallucinate. It supersedes the old fact, non-destructively." |
| 1:57–2:05 | D3 (8s) FRESH SESSION, COMMAND | New session, zero context; Card arrives with WHY. | "New session, zero context. Give it a command: 'Implement feature A.' It doesn't need to ask your stack. Activation spreads, pulling the decisions, conventions, and rules." |
| 2:05–2:08 | D4a (3s) MEMORY OFF | Same question, memory OFF → honest "I don't know." | "Take the memory away…" |
| 2:08–2:09.5 | FLASH (1.5s) | **Goldfish FULLSCREEN.** | *(beat drop)* |
| 2:09.5–2:13 | D4b (3.5s) MEMORY ON | Flip ON → instant answer. | "…and it's a goldfish: 'I don't know.' Flip it back ON… and the genius is back." |
| 2:13–2:17 | D5 (4s) SLEEPS + PINGS | Intention fires; Sleep 5→1. | "Then it sleeps. Replays the day's chaos and compresses messy moments into clean lessons." |

## BEAT 7 — BREAKING IT (2:17–2:30) · S24 (7s) + S25 (6s)

> FLOW IN: warm Sleep snaps cold: "How do you test this?". FLOW OUT:
> explainable tracing → Meta stack.

| TC | ON SCREEN | SAYING |
|---|---|---|
| 2:17–2:24 | S24: **Spidey-pointing FULLSCREEN 2s** cold open → philo terminals (automated adversarial test rig). | "Now — how do you actually test if an agent's memory works? You don't just chat with it and hope for the best. I built an automated test harness: a second agent whose only job is to interrogate the first one, try to trick it, and catch contradictions." |
| 2:24–2:30 | S25: **Graph Trace Debugger** (Cue → Gate → Seeds → 2-Hop Spreading Activation). | "And because the whole memory is an explicit graph, when an agent gets something wrong, you don't guess — you open the graph and trace the exact path to see where the connection failed." |

## BEAT 8 — CLOSE (2:30–2:45) · S26 (6s) + S27/S28 (9s)

> FLOW IN: "what's it built on" → Meta. FLOW OUT: payoff → triumphant finish.

| TC | ON SCREEN | SAYING |
|---|---|---|
| 2:30–2:36 | S26: "BUILT ON META. Muse Spark." + three-bodies strip. V2 lower_meta. | "Built on Meta: powered by Muse Spark via the Meta Model API, with local open-weights fallback. Shipped as one universal MCP server any agent or IDE can mount." |
| 2:36–2:45 | S27 & S28: 3 cards (IDE DEV / PERSONAL AI / COMPANY BRAIN) → close-up, soft smile. Counter → 4, → 5 fireworks. | "The dev whose IDE knows their stack. Personal assistants that actually remember you. Robot brains that accumulate skill. And yes… I used it to remember everything I was mad at my girlfriend for… [beat] …and the one thing that matters: her birthday." Ding #4, #5. |

## OUTRO (2:45–3:00) · S32 (15s)

Clean lockup: TOTTIE. / It just remembers. / repo / 54 papers scrolling under rich music resolution.
"Stop treating AI like an amnesiac. Give it a mind that persists. Tottie. Built on Meta. Build for your world."

## GF-counter ledger (V2 TCs)

| Ding | TC | Line |
|---|---|---|
| 1 | 0:27 | "So this is how my girlfriend feels." |
| 2 | 1:02 | ENCODING beat (girlfriend question context) |
| 3 | — | CUT (merged into close) |
| 4 | 2:40 | "…everything I was mad at my girlfriend for…" |
| 5 | 2:43.5 | "…her birthday." (fireworks variant) |

> V3 spans: `gf_counter_1` 26–60s · `gf_counter_2` 60–158s · `gf_counter_4`
> 158–163s · `gf_counter_final` 163–165s.

## Meme ledger (V2 — 6 fullscreen + PiPs)

| # | Meme | Source → window | Placement | Note |
|---|---|---|---|---|
| 1 | Rage smash FULLSCREEN 1.5s | `rage.mp4` 188–189.5 | S02 local 5–6.5 | Peak flash |
| 2 | Jordan + DIAGNOSIS (full-frame 3s) | `jordan_b.mp4` + A1 line | S03 | Unchanged |
| 3 | Leo pointing PiP | `leo_point.mp4` 12.5–15.5 | S04 local 2–5 | Unchanged |
| 4 | Stonks FULLSCREEN 2s | `stonks.webm` 69–71 | S10 local 0.3–2.3 | NEW — tax punchline |
| 5 | Norman FULLSCREEN 1.5s | `scientist.webm` 2.4–3.9 | S13 local 1–2.5 | Was PiP, now fullscreen |
| 6 | Goldfish FULLSCREEN 1.5s | `goldfish.webm` 4–5.5 | FLASH seg 2:08–2:09.5 | NEW seg |
| 7 | Spidey-pointing FULLSCREEN 2s | `spidey.webm` 8–10 | S24 local 0.5–2.5 | NEW — two philosophers |
| 8–13 | Dory PiP S05 · stinks S06 · X-doubt S08 · Fry S11 · fries S12 · dog S14 · ice cream S15 | (as before) | PiPs unchanged | S14/S15 photos rebuilt into new brain segs |

## Diagram ledger (V2)

| Asset | Beat | Content source |
|---|---|---|
| ENCODING / RETRIEVING cards (S14/S15) | Brain | NotebookLM encoding + retrieval answers |
| Network + CA3 card (S16) | Brain | NotebookLM spreading-activation answer |
| LIVE graph card (S19 joke) | Joke | Same motif, teal (system watching itself) |
| Deep map overlay (S17) | Mapping | cognition.tex roster + neuro-basis table |
| Diagnosis card (S03) | Hook | cognition.tex availability vs accessibility |
| Three-bodies strip (S26) | Tooling | architecture.tex Fig. 1 |
| Eval small print (S25) | Depth | Beamer deck eval numbers |
| Explainer bug (demo) | Demo | PENDING — built after user footage lands |
| `diagrams/figsheet.pdf` | Pool | Verbatim TikZ from docs |

## Meta rubric coverage (V2)

| Rubric | Beat | Proof |
|---|---|---|
| Impact | 8 (2:28–2:38) | Verbatim statement + 6-item applications list |
| Meta Tooling | 8 (2:28–2:32) | Muse Spark / Model API / fallback (VO + lower-third) |
| Technical Depth | 4 + 5 + 7 | Notebook brain science + mapping + trace-back + 22/22 |
| Demo | 6b | User footage (5 beats + ablation + sleep), shot-card protocol |
| Not "basic RAG" | 5 (1:20–1:26) | "3 legs, RRF fused" + write-time flip |

## Current state + revision workflow

> STATUS: V2 visual cut complete on sequence `TOTTIE_V2` (180.0s, 32 V1 clips,
> zero gaps; brain beats rebuilt; 6 fullscreen memes; demo = labeled slates;
> credits roll in). Old `TOTTIE_3MIN` untouched as rollback. Remaining:
> (1) YOUR demo footage per `film/DEMO_RECORD_SCRIPT.md`, (2) VO per
> `film/VO_GUIDE.md`, (3) music bed, (4) explainer-bug composite after (1).

- Retired (not in V2): S19–S23 demo segs, S29 endcard, 5 demo V2 captions.
  Files stay on disk; `_v1snap/` holds the pre-trim V1 set.
- Swap rule unchanged: same filename + same duration = timeline auto-picks it up.
- New-seg generator: `assets_3min/build/build_beats.py` (S14/S15/S16/S19/
  slates/credits). Overlay generator: `build/overlay_diagrams.py`.
- Sidecar: `film/tottie_3min_v2.srt` (V2 TCs; `[USER FOOTAGE]` demo lines).

# TOTTIE — 3-Minute Video: Complete Shot Plan

> **Runtime: 180 seconds exactly.** Every cut, visual, word, animation, SFX, and GF-counter ding
> is specified below. Assets live in `assets_3min/` (SVG sources + 1920×1080 PNG renders).
> FilmCraft project + preview animatic in `assets_3min/film/`.
> **Story:** "I was mad at my agent for forgetting → it's not stupid, it's amnesiac → I copied
> the brain and built it a memory → watch it work → measured, not promised."

## Global spec (applies to every shot)

- **Frame:** 1920×1080, 30fps. Phone-readable text: nothing critical under 48px.
- **Color code:** bio/brain = amber `#E8A33D`; system/Tottie = teal `#14B8A6`; danger/delete =
  red `#E5484D`; background = near-black `#0B0E14`.
- **Fonts:** Helvetica Bold (headlines/captions), Helvetica Regular (body), Monaco (code/terminal).
- **Cut rhythm:** a visual change every 3–7 sec. Jump cuts on every sentence of talking head.
- **GF counter:** top-right from first ding to end card. White pill, black text:
  `girlfriend mentions: N`. +1 = scale-pop animation + soft ding. Total: **5**.
- **Captions:** every key line burned in as kinetic text (word-by-word or stamp-in). Full subtitles
  in the FilmCraft caption track (see plug-in guide).
- **Music:** one bed, stems: RAGE (0:00) → lo-fi pulse (0:20–1:20) → cinematic rise (1:20–2:25) →
  quiet (2:25–2:40) → swell + warm resolve (2:40–3:00). Silence stings at 0:44, 1:39, 2:49.

## Asset map (filename → shot)

| Asset | File | Used in |
|---|---|---|
| Cold-open text | `png/card_coldopen.png` | 0:00 |
| Title card | `png/title_tottie.png` | 0:12 |
| GF counter ×5 | `png/gf_counter_1.png` … `gf_counter_5.png` | 0:30 → 2:55 |
| Name lower-third | `png/lower_name.png` | 0:21 |
| Context-tax chart | `png/chart_context_tax.png` | 0:52 |
| Fries stamp | `png/stamp_fries.png` | 1:00 |
| Q1/Q2/Q3 cards | `png/card_q1.png`, `card_q2.png`, `card_q3.png` | 1:05–1:20 |
| Architecture map | `png/diagram_brain_map.png` | 1:20–1:40 |
| Thesis card | `png/card_thesis.png` | 1:34 |
| RAG-vs-Tottie bar | `png/bar_rag_vs_tottie.png` | 1:26 |
| Demo captions ×5 | `png/demo_cap_*.png` (knows/supersede/associates/ablation/sleep) | 1:40–2:25 |
| Scoreboard | `png/scoreboard.png` | 2:33 |
| Meta lower-third | `png/lower_meta.png` | 2:42 |
| Impact strip (3 icons) | `png/strip_impact.png` | 2:46 |
| End card | `png/endcard.png` | 2:56 |
| Thumbnail | `png/thumbnail.png` | YouTube upload |
| Talking-head slate | `png/slate_head.png` | every `[to YOU]` slot |
| Screen-capture slate | `png/slate_screen.png` | every `[to SCREEN]` slot |

`[to YOU]` = you film talking head here. `[to SCREEN]` = screen recording goes here.
Both slates sit in the FilmCraft timeline as labeled offline clips — replace in place.

---

## BEAT 1 — RAGE HOOK (0:00–0:20)

| TC | ON SCREEN | SAYING | ANIMATION / SFX |
|---|---|---|---|
| 0:00–0:03 | Black. `card_coldopen.png`: **"POV: your agent forgot again."** | *(silence)* | Text slams in, screen shake, bass hit. |
| 0:03–0:12 | `[to SCREEN]` furious typing in Muse chat, keystrokes subtitled huge. 3 outbursts, each faster. | "folder B dammit— how MANY times do I have to tell you man wtffffff. It's 34 employees. I HAVE 34 EMPLOYEES MAN!!! Why am I always reminding youuuu—" | Speed-ramp 1×→1.5×→2×. Keyboard clacks maxed. `title_tottie.png` stamp at 0:12. |
| 0:12–0:15 | Freeze on rage face. Meme: **"stop. you need some help."** | *(record scratch)* | Vine boom. Meme wobble-in. |
| 0:15–0:20 | `[to YOU]` calm. Too calm. `lower_name.png` slides in. | "Have you, or anyone you know, rage-quit a coding session? Flipped OFF… and then back ON… an agent? Join the club, buddy." | Punch-in zoom on "Join the club." |

## BEAT 2 — AMNESIA (0:20–0:45)

| TC | ON SCREEN | SAYING | ANIMATION / SFX |
|---|---|---|---|
| 0:20–0:28 | Montage `[to SCREEN]`: agent re-asking "What is your name?" Calendar timelapse day 1 → 90. | "Our agents have a memory problem. We talk about it today, and two weeks from now it's like… you don't remember what I said?" | TICK on each re-ask. Calendar flips accelerate. |
| 0:28–0:32 | `[to YOU]` deadpan. **`gf_counter_1.png` fades in top-right.** | "So this is how my girlfriend feels." | Ding #1. Hold 1 beat — the audience must NOTICE the counter being born. |
| 0:32–0:40 | Animation: brain labeled AGENT waking in an empty white room, Groundhog loop ×3, faster each time. Text: **"a state persistence problem, not a reasoning problem."** | "Every agent wakes up stateless. No history. No yesterday. All that intelligence — and it fails the baseline of a mind: continuity." | Loop ×3. Color: gray room, amber brain. |
| 0:40–0:45 | `[to YOU]` close-up. Music dips to nothing. | "But people tell me the fix is simple…" | Silence sting. Hard-cut. |

## BEAT 3 — CONTEXT TRAP + BRAIN BABY (0:45–1:05)

| TC | ON SCREEN | SAYING | ANIMATION / SFX |
|---|---|---|---|
| 0:45–0:52 | `[to YOU]` + `chart_context_tax.png` builds live: context ↑ → cost ↑, latency ↑↑, accuracy ↓. Red zone: **"lost in the middle."** | "Just get a 6-million-billion context window, bro. Relax — my Meta money hasn't come in yet. And a bigger window isn't memory, it's an expensive scratchpad. Long context isn't memory. It's a TAX." | `TAX` stamp-in + cash-register sound. Chart arrows draw on. |
| 0:52–0:58 | `[to YOU]` grinning. Meta-stance. | "Or better — a META job? Pro. Put me in the metaverse, let me cook." | Text pop: **hire me @ Meta** + arrow at face. Meme horn (charming, once). |
| 0:58–1:05 | `[to YOU]` drive-thru headset filter. `stamp_fries.png` slams over frame. | "How do we solve context? I'm not. I don't get paid to do that. Put the fries in the bag, bro — that's for the big labs. I asked a smaller, dumber, more dangerous question: what CAN I do?" | Fries stamp = bass hit. Keep headset bit under 3 sec. |

## BEAT 4 — THREE QUESTIONS IN 15 SECONDS (1:05–1:20)

| TC | ON SCREEN | SAYING | ANIMATION / SFX |
|---|---|---|---|
| 1:05–1:10 | `card_q1.png` full-screen: **Q1 — WHAT makes me remember?** B-roll: Street View flythrough of a road. | "What makes ME remember? When my girlfriend tells me about her friend's dog's collar collar — where does my brain say 'remember this'?" | Ding #2 → `gf_counter_2.png`. Whoosh on card slam. |
| 1:10–1:15 | `card_q2.png`: **Q2 — WHEN does it hand it back?** B-roll: walking into kitchen, fridge gasp (1 shot). | "When does it hand it back — the ice cream in the fridge, the cousin who ate it — how does it know NOW is the time?" | Fast zoom into fridge. Harp gliss, 1 sec. |
| 1:15–1:20 | `card_q3.png`: **Q3 — WHY a STORY, not a row?** Mini flashback scene, 2 sec. | "And why does it arrive as a SCENE, not a database row? Not a row. A scene." | **"not a row. a scene."** burned huge. Whip-pan to map. |

## BEAT 5 — THE MAP (1:20–1:40) — centerpiece

| TC | ON SCREEN | SAYING | ANIMATION / SFX |
|---|---|---|---|
| 1:20–1:26 | `diagram_brain_map.png` full-screen. Amber brain (left) → teal system (right). Three lanes light up in sequence: **WATCH → SAVE → HAND BACK.** | "So I drew it. Something to WATCH. Something to SAVE. And something to hand it BACK. RAG doesn't go away — it gets a job inside a larger machine." | `bar_rag_vs_tottie.png` wipes in corner: **"RAG is one leg. This is the whole animal."** Electricity pulse along lanes. |
| 1:26–1:34 | Push into lanes, one by one. Labels pop: **Observer / Scribe+Tiers+Links / Retriever+Card.** Activation spreads like electricity across the graph. | "The Observer asks: worth remembering? The Scribe structures, tiers, and LINKS it — synapses. The Retriever types every turn, spreads activation, and hands back a 400-token Context Card stamped with WHY." | Each pop = soft tick. Spread = rising shimmer. This is the prettiest 8 sec — spend render budget here. |
| 1:34–1:40 | `card_thesis.png`. Everything else falls silent. | "Simulate the brain's solutions. Never simulate its constraints. We didn't copy the forgetting. We copied the finding." | Full silence under the line. 1-beat hold. Smash-cut to demo. |

## BEAT 6 — DEMO: WATCH IT THINK (1:40–2:25) — [META: Demo]

> Pure screen capture + captions + music. Film per `docs/planning/demo_script.tex` shot-card
> protocol: seed + turns + expected Panel states written BEFORE rolling, temp 0, pinned model.

| TC | ON SCREEN | SAYING (VO, quiet) | ANIMATION / SFX |
|---|---|---|---|
| 1:40–1:50 | `[to SCREEN]` Beat 1 — fresh session, old question, instant answer. Panel reacts. `demo_cap_knows.png`: *"It just… knows."* | "Theory is cheap. Watch it think." | Cinematic rise. Panel reaction = the money visual. |
| 1:50–2:00 | `[to SCREEN]` Beat 2 — "I'm vegetarian now" → **SUPERSEDE** flash, old struck through. Trivial "lol nice" → **DISCARD.** `demo_cap_supersede.png`. | "Truth changes — it rewrites, non-destructively. Noise arrives — it throws it away." | Stamp SFX on SUPERSEDE. Q1 tag flickers in corner. |
| 2:00–2:10 | `[to SCREEN]` Beat 3 — "implement feature A" → Context Card with WHY stamps. Brain graph lights the firing path. `demo_cap_associates.png`: *"It doesn't search. It associates."* | "A command, not a question — and it assembles everything a competent person needs." | Music pulse on the spread. Q2 tag in corner. |
| 2:10–2:22 | `[to SCREEN]` Beat 4 — kill session, reopen, knows. **Tottie OFF → "I don't know." ON → knows.** `demo_cap_ablation.png`. | "And the proof: take the memory away, and the genius becomes a goldfish." | Beat DROP on the OFF flip. Clean frame — this clip goes viral. |
| 2:22–2:25 | `[to SCREEN]` Sleep: *"6 episodic → 1 semantic."* `demo_cap_sleep.png`: *"Moments become lessons."* | "Then it sleeps — and generalizes." | Warm grade shift. Q3 tag in corner. |

## BEAT 7 — BREAKING IT (2:25–2:40) — [META: Technical Depth]

| TC | ON SCREEN | SAYING | ANIMATION / SFX |
|---|---|---|---|
| 2:25–2:33 | `[to YOU]` low light, terminal scrolling behind. Split terminals: **PHILOSOPHER 1 (remembers)** vs **PHILOSOPHER 2 (interrogates).** | "Nothing works the first time. So I built a second agent to fight the first one. Two philosophers, arguing about thought — where one is literally mimicking thought. Missed a memory? We trace the graph: formed? surfaced? connected?" | No music, room tone. Trace path draws in red. True-crime-board energy. |
| 2:33–2:40 | `scoreboard.png` slams in: **22/22 ON · 0.0 OFF leak · 4/4 contradictions.** Small print: model ID, temp 0. | "We don't ask you to trust it. We measure it. 22 scenarios, memory-ON versus OFF. 22 of 22. Zero leak. Four for four." | Sports horn per stat. Small print readable on pause — judges screenshot it. |

## BEAT 8 — CLOSE (2:40–3:00) — [META: Tooling + Impact]

| TC | ON SCREEN | SAYING | ANIMATION / SFX |
|---|---|---|---|
| 2:40–2:46 | `[to YOU]` standing. `lower_meta.png`: **Built on Muse Spark · Meta Model API.** Background washes Meta-blue. | "Built on Meta. Observer, Scribe, brain — Muse Spark via the Meta Model API, local open-weights fallback. Build for Your World: one MCP server, any agent mounts it." | Say "Build for Your World" verbatim. Lower-third slides, doesn't pop. |
| 2:46–2:50 | `strip_impact.png`: 3 icons wipe in — **IDE dev · personal AI · company brain.** | "The dev whose IDE knows the stack. The assistant that knows YOU. The company brain that remembers Server C." | 2 sec per icon. Music swelling. |
| 2:50–2:56 | `[to YOU]` close-up, soft smile. Counter pulses. | "So I used it to remember everything I was mad at my girlfriend for…" Ding #4. "…and the one thing that matters: her birthday." Ding #5 — counter fireworks. | Music cuts at 2:49. Two dings, second with sparkle. Last joke — land it, get out. |
| 2:56–3:00 | `endcard.png`: **TOTTIE. It just remembers.** + repo link. 1-sec rage-face stinger. | *(silence)* | Loop closes: ends where it began. Cut on the stinger face. |

## GF-counter ledger (locked to this edit)

| Ding | TC | Line |
|---|---|---|
| 1 | 0:30 | "So this is how my girlfriend feels." |
| 2 | 1:07 | "…my girlfriend tells me about her friend's dog's…" |
| 3 | — | CUT for 3-min (was the rom-com "favorite memories" — merged into close) |
| 4 | 2:52 | "…everything I was mad at my girlfriend for…" |
| 5 | 2:55 | "…her birthday." |

> Counter PNGs are numbered 1,2,4,5 + final-fireworks variant to match this ledger. If you
> restore a mention, recount in edit order and re-render that PNG (SVG sources included).

## Meta rubric coverage (3-min)

| Rubric | Beat | Proof |
|---|---|---|
| Impact / Build for Your World | 8 (2:40–2:50) | Statement verbatim + 3 beneficiaries |
| Use of Meta Tooling | 8 (2:40–2:46) | Muse Spark / Meta Model API / open-weights fallback |
| Technical Depth | 5 + 7 | Map + trace-back + 22/22 ON/OFF + quarantine/SUPERSEDE |
| Demo | 6 | 4 beats + ablation money shot + Sleep, shot-card protocol |
| Not "basic RAG" | 5 (1:20–1:26) | "RAG is one leg. This is the whole animal." + write-time flip |

## Plug-in guide (where YOU go later)

> STATUS: DONE except VO + music. V1 = 24 motion segments + 5 REAL demo recordings
> (live system: birthday recall conf 0.98, real SUPERSEDE, COMMAND kit with WHY lines,
> ON→OFF→ON ablation, sleep 5 episodic → 1 semantic). A1 = 24 SFX. Subtitles are
> burned into every segment (SRT sidecar kept for YouTube).
> What remains: (1) your VO per `film/VO_GUIDE.md`, (2) a music bed.
> Talking head is OPTIONAL — the video stands alone with VO.

Built artifacts (all exist now — verified by frame renders in `assets_3min/film/`):

- `assets_3min/svg/` — 28 editable vector sources (cards, overlays, map, slates, thumbnail).
- `assets_3min/png/` — 28 renders (27× 1920×1080 + 1× 1280×720 thumbnail), via VectorCraft.
- `assets_3min/seq/` — 5,400 rendered animation frames (29 segments, PIL + Helvetica).
- `assets_3min/seg/` — 29 motion segments as H.264 (kinetic VO, chart draw-on, map pulse,
  scoreboard slams, demo containers).
- `assets_3min/sfx/` — 9 synthesized original SFX (ding, boom, tick, stamp, horn, whoosh,
  cash, drop, final-ding). No samples, no copyright.
- `assets_3min/film/tottie_3min.fcproj` — FilmCraft project, sequence `TOTTIE_3MIN`:
  V1 = 29 motion segments (back-to-back, 180.0s, zero gaps), V2 = 10 overlays
  (lower-thirds, demo captions, bars), V3 = 4 GF-counter spans (unbroken 28→176s),
  A1 = 24 placed SFX, caption track with 26 timed subtitles, 31 markers.
- `assets_3min/film/tottie_3min.srt` — subtitle sidecar (also imported in-project).
- `assets_3min/film/VO_GUIDE.md` — the VO record script (timecode-locked, delivery notes).
- `assets_3min/film/visual_cut.mp4` — full visual cut (motion + SFX, no VO yet).
- `assets_3min/film/animatic_preview.mp4` — earlier slate-based timing preview (superseded).
- `assets_3min/film/thumbnail.jpg` — YouTube thumbnail (90% JPEG, via PhotoCraft).
- `assets_3min/film/export_preset.json` — delivery settings for the final export.

Steps:

1. Open `assets_3min/film/tottie_3min.fcproj` in FilmCraft. Read the yellow SLOT markers —
   each carries its filming note (shot, SFX, timing) in the comment field.
2. Film talking head per the SAYING column; record screen per `docs/planning/demo_script.tex`
   shot cards. Drop each take onto its slate clip (Alt-replace keeps timing).
3. Retouch SRT timing to your actual delivery; keep captions as sidecar, NOT burned in —
   burned-in subs collide with the demo caption bars in beat 6 (visible in the animatic).
4. Music bed + SFX per the ANIMATION/SFX column. Rose markers guard the silence stings at
   0:44, 1:39, 2:49 — protect them.
5. Recount GF dings against the final edit; counter PNGs swap 1:1 (SVG sources included).
   Titles already clear the counter zone (x ≥ 1300, y ≤ 140) — keep new graphics clear too.
6. Export per `film/export_preset.json`. Upload with `thumbnail.jpg`.


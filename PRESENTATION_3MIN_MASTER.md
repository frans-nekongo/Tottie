# TOTTIE — 3-MINUTE HACKATHON MASTER PRODUCTION PLAN
**Meta Global AI Developer Hackathon 2026 — Indie Developer Track**  
**Runtime:** 180.0s (0:00 – 3:00) | **Resolution:** 1080p (1920×1080 @ 30fps) | **Status:** Locked & Synchronized

---

## 1. Production Overview & Creative Direction

### The Tone & Persona
- **Authentic Builder Voice:** Zero corporate robotic fluff, zero AI buzzword salad. You are a developer talking directly to fellow developers and judges who have felt the exact same rage when agents forget their context.
- **Relatable Humour Layered In:** From the Jordan PSA, Leo pointing, and "put the fries in the bag" underdog pivot, to the running Girlfriend Counter and the Spiderman standoff.
- **Neuroscience Receipts:** Rooted firmly in the 54 neuroscience papers documented in `cognition.tex`. We explain how biological memory works *first* (predictive coding, spreading activation, CA3 autoassociation), then show the exact software components we built to emulate those solutions.
- **Explainable Testing Over Fake Metrics:** We replaced the blind "22/22 scoreboard" with our **Automated Interrogation Harness** (two adversarial agents arguing) and the **Graph Trace Path Debugger** (inspecting missing memory like a stack trace).

---

## 2. Complete Act-by-Act Master Breakdown

### ACT I — THE DISEASE & AMNESIA LOOP (0:00 – 0:42)

| Timecode | On-Screen Visual | Audio / SFX | Script / Voiceover | Assets & Animation Notes |
| :--- | :--- | :--- | :--- | :--- |
| **0:00–0:03** | Pure black. Kinetic typography slams onto screen: **"POV: your agent forgot again."** | Heavy cinematic sub-bass drop (`boom_sub.wav`). Total silence after. | *(No dialogue — let the audience sit in the relatable pain for 2 seconds)* | Bass drop. Screen-shake on text impact. Minimalist, intense. |
| **0:03–0:12** | Smash-cut to terminal screen recording: cursor aggressively typing. Keystrokes subtitled huge as you type. Speed-ramps faster. | Aggressive mechanical keyboard clatter maxed in mix. Needle-scratch record scratch at 0:11. | *"Folder B, dammit—how MANY times do I have to tell you, man?! It's 34 employees. I HAVE 34 EMPLOYEES, MAN! Why am I always reminding youuuu—"* | Red flash on screen at 0:11. Freeze-frame on rage typing. |
| **0:12–0:15** | Fullscreen meme takeover: Michael Jordan PSA. | Jordan audio: *"Stop it. Get some help."* + Vine boom. | *(Jordan audio carries the beat)* | `assets_3min/memes/jordan_psa.mp4`. Clean cut, deadpan pause. |
| **0:15–0:20** | Talking head cut. Calm, deadpan smile looking directly into lens. Picture-in-picture Leonardo DiCaprio pointing meme. | Smooth lo-fi chillhop beat fades in subtly. | *"Have you ever rage-quit a coding session? Flipped an agent OFF… and back ON? Join the club, buddy."* | `assets_3min/memes/leo_point.mp4` PiP bottom right. Punch-in zoom on "buddy." |
| **0:20–0:26** | Montage of terminal chats asking repetitive questions: *"What is your name?"*, *"What stack?"* Calendar timelapse flips: Day 1 → Day 90. | Comedy typewriter tick sound on each calendar flip. | *"Our agents have a memory problem. Two weeks later, it's like we never talked."* | Kinetic text overlay: *"Wakes up with zero yesterday."* |
| **0:26–0:29** | Deadpan stare directly into lens. Stinks meme pops up in corner. | Pop sound + clean register ding. | *"So this is how my girlfriend feels."* | `assets_3min/memes/stinks.webm`. **GF Counter: 1** badge appears bottom-left with ding. |
| **0:29–0:37** | Motion graphic / animation: illustrated brain labeled "AGENT" waking up in bed with empty thought bubble, 3 days in a row (Groundhog Day loop). | Monotonous alarm clock beep loop. | *"Every agent wakes up stateless. No history. No yesterday. All that intelligence — and zero continuity."* | Stamped across screen: **"State persistence problem, not a reasoning problem."** |
| **0:37–0:42** | Talking head. Smug expression, hands raised in air. Meme flash: LA Noire "Press X to Doubt". | Low synth riser building tension. Comic record stop at 0:41. | *"But people tell me the fix is simple…"* | `assets_3min/memes/xdoubt.webm` flash. Cut to silence right before 0:42. |

---

### ACT II — THE CONTEXT TAX & UNDERDOG PIVOT (0:42 – 1:00)

| Timecode | On-Screen Visual | Audio / SFX | Script / Voiceover | Assets & Animation Notes |
| :--- | :--- | :--- | :--- | :--- |
| **0:42–0:49** | Talking head holding phone, sarcastically mock-quoting. Cut to Stonks meme. Slide in Context Tax diagram (Figure 1: Token Cost vs Latency hockey-stick curve). | Comic cartoon slide-whistle up followed by an explosion sound. | *"Just get a 6-million-billion context window, bro. Except every token costs money. Every turn slows down. Shoving your entire life into the prompt isn't memory. It's a bill."* | `assets_3min/memes/stonks.webm`. Overlay: `figsheet_p1.png` (Cost vs Latency exponential curve). |
| **0:49–0:53** | Talking head looking up thoughtfully, smiling earnestly. | Hopeful upbeat chime. | *"Look, if Meta wants to give me a million dollars to burn on compute, put me in the metaverse right now."* | Playful Meta logo pop-up. |
| **0:53–0:57** | Fullscreen meme: McDonald's employee putting fries in bag. Bold text: **"PUT THE FRIES IN THE BAG, BRO."** | Fast cash register "CHA-CHING" sound. | *"— but my Meta money hasn't landed yet. So until then? I'll just put the fries in the bag."* | `assets_3min/memes/fries.jpg`. Hard cut. Authentic comedic timing. |
| **0:57–1:00** | Willem Dafoe "You know, I'm something of a scientist myself" meme. Cut to split-screen of stack of 54 neuroscience papers. | Academic brass fanfare sting. | *"So what CAN I do? Build the real thing."* | `assets_3min/memes/norman.jpg`. Slide in: *"54 Cognitive Science Papers"* counter. |

---

### ACT III — HOW THE BRAIN SOLVED IT: 3 QUESTIONS & SOFTWARE MAPPING (1:00 – 1:38)

| Timecode | On-Screen Visual | Audio / SFX | Script / Voiceover | Assets & Animation Notes |
| :--- | :--- | :--- | :--- | :--- |
| **1:00–1:07** | Split screen: Left = Cute puppy photo (`dog.jpg`). Right = Neural spike animation with prediction error curve. | High-tech sonar pulse. Gentle UI click. | *"How does YOUR brain do it? First: what's worth keeping? When your girlfriend's friend's dog bites your shoe — you don't replay the whole week. The brain notices SURPRISE."* | **GF Counter: 2** appears with chime. Graphic highlights: *Predictive Coding & Salience Gate*. |
| **1:07–1:14** | Visual: Open refrigerator with ice cream carton (`icecream.jpg`). Neural network activating spreading light rays to "2am snack". | Soft swoosh + electrical hum. | *"Second: how does it come back? You open the fridge, see ice cream — boom: Tuesday night, 2 AM, the kitchen counter. Cues drag memories up by association."* | Motion graphic: Spreading activation paths highlighting linked memory nodes. |
| **1:14–1:20** | Visual: 3D synaptic network graph. Nodes lighting up other nodes through weighted edges. | Digital connection beep sequence. | *"Third: how is it all wired together — so one memory drags the next one up with it? Synaptic links. A web, not a filing cabinet."* | Graph visualization showing autoassociative CA3 pattern completion. |
| **1:20–1:32** | Architecture Reveal: Animated split diagram mapping biological brain structures directly to Tottie modules (Figure 3: Cognitive Mapping). | Rhythmic, confident tech beat kicks in. | *"Fifty-four papers later, we mapped it. The brain notices — that's the Observer, filtering for surprise. It files and links — that's the Scribe, weaving memory tiers. It fetches on cue — that's the Retriever. RAG finally got a job."* | `assets_3min/diagrams/figsheet_p3.png`. Animated callouts: **Observer** (Predictive Filter) $\rightarrow$ **Scribe** (Tiered Storage & Graph Edges) $\rightarrow$ **Retriever** (Spreading Activation). |
| **1:32–1:38** | Clean minimalist slide with typography: *"Simulate the brain's solutions. Never simulate its constraints."* | Music dips to near-silence. Bass sub-hit on "finding." | *"Simulate the brain's solutions. Never simulate its constraints. We didn't copy the forgetting. We copied the finding."* | Kinetic typography. Hard cut to terminal on "finding." |

---

### ACT IV — THE LIVE DEMONSTRATION: BUILD A BRAIN YOU CAN LOOK AT (1:38 – 2:17)

| Timecode | On-Screen Visual | Audio / SFX | Script / Voiceover | Assets & Animation Notes |
| :--- | :--- | :--- | :--- | :--- |
| **1:38–1:43** | Split-screen workspace: Left = Real terminal session. Right = Live 3D force-directed knowledge graph (`tottie-web` / three.js canvas). | Uplifting developer synth pulse. | *"All theory. Servers humming in the dark. How do you WATCH a memory form? Build a brain you can look at."* | Full UI showcase. Left 55% Terminal, Right 45% 3D Graph. |
| **1:43–1:50** | **Demo 1 — Learning:** User types in terminal: *"We use pnpm, never npm. Auth is Supabase."* Right side: Blue node pulses and spawns in graph with connecting edges. | Crisp UI notification ping on node creation. | *"Tell it a rule once. Watch the right side file it: a new node appears, connects to the stack, and stays there."* | Camera zooms slightly into the 3D node labeled `Stack Rule: pnpm + Supabase`. |
| **1:50–1:57** | **Demo 2 — Truth Changes:** User types: *"Actually, we migrated auth to Lucia."* Right side: Old Supabase node fades grey (archived), new Lucia node glows active green with `supersedes` link. | Subtle electronic rewind sound followed by chime. | *"Truth changes. Tell it we switched to Lucia — watch the old node fade, superseded, not deleted. Audit trails intact."* | Visual indicator: Red dotted arrow representing `superseded_by` edge. |
| **1:57–2:05** | **Demo 3 — Associative Command:** User asks high-level prompt: *"Set up login for the mobile app."* Terminal automatically pulls both the pnpm rule and Lucia auth without being told. | Fast data-stream clicking sound. | *"A command, not a question. It pulls the pnpm rule AND the new auth node together — without me mentioning either one."* | Nodes highlight yellow as they are retrieved into the context window. |
| **1:05–2:09** | **Demo 4 — Memory Ablation (The Goldfish Test):** Toggle switch turns Tottie Memory **OFF**. Terminal runs same prompt: agent immediately outputs standard generic `npm install` and broken code. | Comic sad trombone or buzz sound. Quick goldfish meme flash. | *"Take the memory away… and the goldfish is back."* | Screen overlay flashes red: **MEMORY OFF (STATELESS BASELINE)**. |
| **2:09–2:13** | Toggle switch turns Tottie Memory **ON**. Agent instantly generates correct customized project code. | Uplifting synth chime. | *"Turn it back on — and it's a senior engineer again."* | Screen overlay flashes green: **MEMORY ACTIVE (PERSISTENT STATE)**. |
| **2:13–2:17** | **Demo 5 — Sleep Consolidation:** Terminal triggers `tottie consolidate`. Graph nodes cluster together; episodic noise collapses into clean semantic hierarchy. | Gentle chime + low harmonic hum. | *"Then it sleeps. Offline consolidation merges the noise, builds generalizations, and prunes dead weight."* | 3D graph cluster animation: 12 individual episodic points merge into 2 structured semantic clusters. |

---

### ACT V — ADVERSARIAL TESTING & GRAPH TRACE DEBUGGER (2:17 – 2:36)

| Timecode | On-Screen Visual | Audio / SFX | Script / Voiceover | Assets & Animation Notes |
| :--- | :--- | :--- | :--- | :--- |
| **2:17–2:23** | Meme flash: Two Spidermen pointing at each other (`spidey.webm`). Slide in Figure 4: Automated Interrogation Harness diagram. | Comic dual trumpet fanfare. | *"Nothing works the first time. So I built a second agent to fight the first. An automated interrogation harness stress-testing recall."* | `assets_3min/memes/spidey.webm`. Diagram showing: **Agent A (Prover)** vs **Agent B (Challenger)** with judge evaluator. |
| **2:23–2:30** | Screen recording: Terminal running automated recall suite (`tests/eval_harness.py`). UI shows test passes with clean execution logs. | Fast, rhythmic testing clicks and pass pings. | *"Instead of hoping it remembered, the challenger probes contradictory edge cases, context shifts, and multi-hop questions."* | Clean pass indicators: Green checkmarks streaming down terminal output. |
| **2:30–2:36** | UI Card: **Graph Trace Path Debugger** (`scoreboard.png`). Visual trace showing exact recall path: Cues $\rightarrow$ Spreading Activation $\rightarrow$ Top-K Selection. | Clean tech affirmative ping. | *"And if a memory ever misses? We don't guess. We trace the graph path like a stack trace: did it fail to form, fail to surface, or fail to connect?"* | `assets_3min/png/scoreboard.png`. Step-by-step visual diagnostic: *1. Cue Extraction $\rightarrow$ 2. Threshold Check $\rightarrow$ 3. Edge Traversal*. |

---

### ACT VI — BUILT ON META & THE GIRLFRIEND CLOSER (2:36 – 3:00)

| Timecode | On-Screen Visual | Audio / SFX | Script / Voiceover | Assets & Animation Notes |
| :--- | :--- | :--- | :--- | :--- |
| **2:36–2:42** | Meta Hackathon Graphic: Llama 3 models integrated via Model Context Protocol (MCP) server. Logos: Meta + Muse Spark. | Big, triumphant cinematic build. | *"Built on Meta. Muse Spark. Llama models running over open MCP standards. Build for Your World — not just for your session."* | Screen badges: **Meta Llama 3**, **Model Context Protocol (MCP)**, **Muse Spark Hackathon**. |
| **2:42–2:48** | Rapid-fire icon montage: 1. Code Editor / IDE $\rightarrow$ 2. Autonomous Agent $\rightarrow$ 3. Physical Robot / Embodied AI $\rightarrow$ 4. Enterprise Knowledge Base. | Quick dynamic whooshes on each icon pop. | *"For the developer who's tired of repeating themselves. For the company brain. For robot brains that actually learn as they move."* | Rapid 4-quadrant screen split with sleek modern icons. |
| **2:48–2:55** | Talking head. Deadpan sincere delivery directly to camera. GF Counter pops from 4 to 5 with celebratory party blower / fanfare. | Music drops out completely at 2:53 for comic silence. Party horn at 2:54. | *"So I used it to remember everything I was mad at my girlfriend for… (deadpan beat) …and the one thing that actually matters: her birthday."* | **GF Counter: 5 (SAVED)** badge lights up with confetti. Ultimate comedic payoff. |
| **2:55–3:00** | End Slate: GitHub repo link, QR code, credits, and rolling strip of the 54 neuroscience papers. | Warm, resolved lo-fi outro music. Final clean chord. | *(No voiceover — smooth musical fade out as credits roll)* | GitHub URL: `github.com/fransnekongo/Tottie`. Subtitle: *"Tottie — Persistent Agent Memory Architecture."* |

---

## 3. Screen Recording & Production Checklist

### Video Capture Settings
- **Resolution:** 1920×1080 (1080p)
- **Frame Rate:** 30.0 fps (or 60.0 fps downsampled)
- **Terminal Theme:** High-contrast dark theme (e.g. Tokyo Night or Catppuccin Mocha), font size 18pt+ for crisp mobile & monitor readability.

### Footage to Capture (Checklist)
- [ ] **Rage Typing (0:03–0:12):** Screen capture of rapid keystrokes typing in terminal chat: `"Folder B, dammit—how MANY times do I have to tell you..."`
- [ ] **Talking Head Footage (0:15, 0:26, 0:42, 0:49, 0:57, 2:48):** Centered framing, good lighting, expressive deadpan comedic delivery on girlfriend punchlines and "put the fries in the bag".
- [ ] **Live Split-Screen Demo (1:38–2:17):**
  - Left half: Terminal running MCP agent interaction (`orch` / CLI).
  - Right half: Browser window showing 3D knowledge graph viewer (`http://localhost:3000` or three.js visualizer).
  - Beat 1: Ingesting pnpm & Supabase rule (watch node spawn).
  - Beat 2: Updating rule to Lucia auth (watch node turn grey & new node link).
  - Beat 3: Associative recall prompt (watch nodes light up and inject).
  - Beat 4: Memory ablation toggle (goldfish baseline failure vs memory active success).
  - Beat 5: Consolidation command (`tottie consolidate` / cluster merge).
- [ ] **Test Harness & Trace Capture (2:23–2:36):** Terminal capture of `python -m pytest tests/eval_harness.py` showing adversarial interrogations passing.

---

## 4. Asset Library & Directory Map

All production assets are pre-generated, verified, and mapped in the workspace:

| Asset Name | File Path | Usage & Description |
| :--- | :--- | :--- |
| **Meme: Jordan PSA** | `assets_3min/memes/jordan_psa.mp4` | Act I (0:12) — "Stop it. Get some help." |
| **Meme: Leo Pointing** | `assets_3min/memes/leo_point.mp4` | Act I (0:15) — Relatable developer recognition |
| **Meme: Stinks** | `assets_3min/memes/stinks.webm` | Act I (0:26) — Girlfriend amnesia joke #1 |
| **Meme: Press X to Doubt** | `assets_3min/memes/xdoubt.webm` | Act I (0:37) — Mocking the context window hype |
| **Meme: Stonks** | `assets_3min/memes/stonks.webm` | Act II (0:42) — Context window billing costs |
| **Meme: Fries in the Bag** | `assets_3min/memes/fries.jpg` | Act II (0:53) — Underdog startup pivot |
| **Meme: Norman Scientist** | `assets_3min/memes/norman.jpg` | Act II (0:57) — "Something of a scientist myself" |
| **Meme: Spidermen Pointing** | `assets_3min/memes/spidey.webm` | Act V (2:17) — Adversarial agent interrogation |
| **Figure 1: Context Tax** | `assets_3min/diagrams/figsheet_p1.png` | Act II (0:45) — Token Cost vs Latency curve |
| **Figure 2: Groundhog State** | `assets_3min/diagrams/figsheet_p2.png` | Act I (0:32) — Stateless agent waking loop |
| **Figure 3: Cognitive Mapping** | `assets_3min/diagrams/figsheet_p3.png` | Act III (1:20) — Biology to Tottie Architecture |
| **Figure 4: Interrogation Suite** | `assets_3min/diagrams/figsheet_p4.png` | Act V (2:20) — Adversarial Harness & Trace |
| **Scoreboard / Trace Card** | `assets_3min/png/scoreboard.png` | Act V (2:30) — Graph Trace Path Debugger Card |
| **Complete FilmCut Render** | `assets_3min/film/tottie_3min_v2_cut.mp4`| Full 180s concatenated preview cut |
| **FilmCraft Project File** | `assets_3min/film/tottie_3min.fcproj` | Native FilmCraft project with all timeline markers |
| **Synchronized Subtitles** | `assets_3min/film/tottie_3min_v2.srt` | 28 millisecond-precise subtitle cues |

---

## 5. FilmCraft Project Verification

The native FilmCraft timeline at `assets_3min/film/tottie_3min.fcproj` contains 36 chapter markers perfectly aligned to these timecodes:
- `0.00s`: BEAT 1 RAGE HOOK (`S01`–`S04`)
- `20.00s`: BEAT 2 AMNESIA (`S05`–`S09`)
- `42.00s`: BEAT 3 CONTEXT TRAP (`S10`–`S14`)
- `60.00s`: BEAT 4 THE BRAIN (`S15`–`S17`)
- `80.00s`: BEAT 5 THE MAPPING (`S18`)
- `98.00s`: BEAT 6 JOKE + DEMO (`S19`–`S24`)
- `137.00s`: BEAT 7 BREAKING IT (`S25`)
- `148.00s`: BEAT 8 CLOSE (`S26`–`S27`)
- `165.00s`: CREDITS (`S28`)

# VO RECORD GUIDE — read this, nothing else needed

> The video is finished. All visuals, motion, SFX, captions are in the timeline.
> You record ONE voiceover track, straight through, matching these timecodes.
> Import it to Audio 2, nudge to sync, export. Done.
>
> Setup: quiet room, phone mic 15cm away is fine. Record 3 takes, keep the angriest
> take for Beat 1 and the softest for the close. Pace: the timecodes already fit a
> natural read — if you run long on a line, the video holds (kinetic text waits).

## How to sync

1. Open `tottie_3min.fcproj`, sequence `TOTTIE_3MIN`.
2. Import your VO wav/mp3, drop on **Audio 2** starting at 0:00.
3. Line 1 starts at 0:03. Align your first word to the first typing burst.
4. The 3 rose markers (0:44, 1:39, 2:49) are SILENCE — leave those gaps empty.
5. Export per `export_preset.json`.

## The script (timecode-locked)

| TC | Say (verbatim) | Delivery |
|---|---|---|
| 0:03–0:12 | "Folder B, dammit— how MANY times do I have to tell you, man?! It's 34 employees. I HAVE 34 EMPLOYEES, MAN! Why am I always reminding youuuu—" | FURIOUS. Real rage. 3 bursts, faster each time. |
| 0:15–0:20 | "Have you, or anyone you know, rage-quit a coding session? Flipped off… and then back on… an agent? Join the club, buddy." | Calm. Too calm. Smile on "buddy." |
| 0:20–0:28 | "Our agents have a memory problem. We talk about it today, and two weeks from now it's like… you don't remember what I said?" | Conversational, building. |
| 0:28–0:32 | "So this is how my girlfriend feels." | Deadpan. Let the ding land. |
| 0:32–0:40 | "Every agent wakes up stateless. No history. No yesterday. All that intelligence — and it fails the baseline of a mind: continuity." | Slow, serious. Documentary voice. |
| 0:40–0:45 | "But people tell me the fix is simple…" | Trailing off. Into the mic. Then SILENCE. |
| 0:45–0:54 | "Just get a six-million-billion context window, bro. Relax — my Meta money hasn't come in yet. And a bigger window isn't memory, it's an expensive scratchpad. Long context isn't memory. It's a tax." | Mocking, then sharp on "tax." |
| 0:54–0:58 | "Or better — a META job? Pro. Put me in the metaverse, let me cook." | Grinning. Charming. |
| 0:58–1:05 | "How do we solve context? I'm not. I don't get paid to do that. Put the fries in the bag, bro — that's for the big labs. I asked a smaller, dumber, more dangerous question: what CAN I do?" | Fries line = throwaway. Last line = quiet, dangerous. |
| 1:05–1:10 | "Question one: WHAT makes me remember? When my girlfriend tells me about her friend's dog's collar collar — where does my brain say 'remember this'?" | Fast, punchy. Keep the stutter. |
| 1:10–1:15 | "Question two: WHEN does it hand it back? The ice cream, the fridge, the cousin — how does it know NOW is the time?" | Same energy. |
| 1:15–1:20 | "Question three: WHY a story, not a row? Not a row. A scene." | Slow down on the last four words. |
| 1:20–1:26 | "So I drew it. Something to watch. Something to save. And something to hand it back. RAG doesn't go away — it gets a job inside a larger machine." | Builder energy. Proud. |
| 1:26–1:34 | "The Observer asks: worth remembering? The Scribe structures, tiers, and links it — synapses. The Retriever spreads activation and hands back a Context Card stamped with why." | Flowing, one breath per sentence. |
| 1:34–1:40 | "Simulate the brain's solutions. Never simulate its constraints. We didn't copy the forgetting. We copied the finding." | THE line. Slow. Let silence sit after. |
| 1:40–1:50 | "Theory is cheap. Watch it think. It just… knows." | Quiet. Let the demo breathe. |
| 1:50–2:00 | "Truth changes — it rewrites, non-destructively. Noise arrives — it throws it away." | Narrating, light. |
| 2:00–2:10 | "A command, not a question — and it assembles everything a competent person needs." | Same. |
| 2:10–2:22 | "And the proof: take the memory away, and the genius becomes a goldfish." | Pause before "goldfish." Smile. |
| 2:22–2:25 | "Then it sleeps — and generalizes." | Warm. |
| 2:25–2:33 | "Nothing works the first time. So I built a second agent to fight the first one. Two philosophers, arguing about thought — where one is literally mimicking thought." | Honest. Tired smile. No music under you. |
| 2:33–2:40 | "We don't ask you to trust it. We measure it. 22 scenarios, memory on versus off. 22 of 22. Zero leak. Four for four." | Confident. Staccato on the numbers. |
| 2:40–2:46 | "Built on Meta. Observer, Scribe, brain — Muse Spark via the Meta Model API, local open-weights fallback. Build for Your World: one MCP server, any agent mounts it." | Say "Build for Your World" verbatim, clearly. |
| 2:46–2:50 | "The dev whose IDE knows the stack. The assistant that knows you. The company brain that remembers Server C." | Aspirational. Rising. |
| 2:50–2:56 | "So I used it to remember everything I was mad at my girlfriend for… and the one thing that actually matters: her birthday." | Soft. Pause before "and." This is the last joke — land it, get out. |
| 2:56–3:00 | *(silence)* | Let the end card ring. |

## What remains (everything else is in the timeline)

1. **This VO.** Only your voice works. (That's this file.) Drop it on Audio 2.
2. **Music bed.** Pick one track (cinematic-rising → lo-fi → swell per the plan's music
   column) and lay it on Audio 3 under everything. Keep the 3 rose-marker silences empty.
3. **Nothing else.** The 1:40–2:25 demo is REAL recorded footage of the live system
   (raw takes in `assets_3min/demo_raw/b*.webm`, cut to slot lengths in `seg/S19–S23`).
   Open `tottie_3min.fcproj`, press play: video + captions + SFX all run. Add VO + music,
   export per `export_preset.json`, upload with `thumbnail.jpg`.

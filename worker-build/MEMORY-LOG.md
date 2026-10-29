# Atlas Memory Log — minisite builder mission

Session prefix: `atlas-`. Owner: `owner_local`. Transport: MCP stdio via
`mcp_mem.py` (own client, stdlib only). Fallback: none so far.

Every memory call: args summary, what returned, verdict
(helped / wrong / useless).

---

## 1. memory.recall — resuming: is there past context for this mission?
- Args: query="Atlas minisite markdown-to-HTML builder mission context", session_id="atlas-day1", k=8
- Returned: mode=ranked, confidence=0.107, abstain=true, story="no confident match (0.11 < 0.35) — abstained". Card still contained seed-demo identity facts (Amara, freelance designer) with hits scoring ~0.016.
- Verdict: USELESS content but CORRECT abstain flag. Nothing mission-relevant exists yet, which is expected on day one. I honored abstain=true and ignored the card. (Note: card carries content even when abstaining — host must check the flag, per the context-card prompt rules.)

## 2. memory.remember — DECISION: minisite architecture
- Args: text="DECISION (atlas-day1, minisite mission): stdlib-only single-package design..." (builder.py parser + site builder, __main__.py CLI, tests/ prove each feature), session_id="atlas-day1"
- Returned: action="NEW n=1 keep sal=0.90 sur=0.52", verdict keep, candidate kind=decision tier=knowledge, tags=[design, work, minisite, atlas-day1, python, stdlib, markdown]
- Verdict: HELPED — Scribe kept it, classified correctly as a decision, and minted mission tags (minisite, atlas-day1) I can probe later.

## 3. memory.intend — run full suite before declaring done
- Args: content="Run the full minisite pytest suite and fix every failure before declaring the mission done.", event_cue="minisite tests written"
- Returned: id=cb2d4f8a-..., content echoed, event_cue kept, time_cue null
- Verdict: HELPED — registered cleanly with an id. Will check whether it fires on a later recall (fired_intentions was empty in call #1, before this existed).

## 4. memory.remember — LESSON: 2 pytest bugs and fixes
- Args: text="LESSON (atlas-day1, minisite): pytest caught 2 real bugs. (1) escape-before-link-match broke title links (&quot;) ... (2) unclosed fence phantom newline ... shared emit_fence ... 24/24 green", session_id="atlas-day1"
- Returned: action="NEW n=2 keep sal=0.90 sur=0.35 n=2", 2 lesson candidates (procedural): escape-entities principle + fence-strip, both tagged atlas-day1/minisite
- Verdict: HELPED classification, but see #5 — only half of it actually persisted (as discovered next).

## 5. memory.probe tag="minisite" — inspect my room
- Args: tag="minisite"
- Returned: 2 memories: the #2 decision + the fence-strip lesson. The escape-entities lesson candidate from #4 is MISSING despite "NEW n=2".
- Verdict: HELPED (probe itself is fast ~4.5s and truthful) but exposed a WRONG: remember claimed n=2 kept, room shows n=1 of the two. Second probe of tag="atlas-day1" confirmed the same 2 rows.

## 6. memory.recall — hunt the missing lesson
- Args: query="link title regex escaped entities lesson", session_id="atlas-day1", k=8
- Returned: abstain=true, confidence=0.13, hits led by my fence lesson + decision at scores ~0.016, then seed-demo rows. No trace of the escape-entities lesson. fired_intentions=[] (my #3 intention's cue "minisite tests written" not mentioned, so no fire expected — untested).
- Verdict: USELESS for retrieval (near-verbatim query of my own minutes-old content scores 0.016 and abstains; vector ranking looks near-random at this scale) but USEFUL as evidence that the lesson is genuinely gone, not just untagged. Also: card again carries seed identity lines while abstaining — flag discipline required.

## 7. memory.remember — re-store the lost escape-entities lesson (repair)
- Args: single-lesson text on escape-early/regex entities, session_id="atlas-day1"
- Returned: action="NEW n=1 keep sal=0.90", one procedural lesson, tags=[atlas-day1, minisite]
- Follow-up probe of tag="minisite": now 3 rows (decision + both lessons). Repair verified.
- Verdict: HELPED. Hypothesis for #5: multi-candidate turns may persist only one candidate (or reconcile silently drops one) — single-lesson turns persist reliably. Flagging, not concluding; n=1.

## 8. memory.sleep — natural break: build done, 24/24 green
- Args: {}
- Returned: available=true, episodes_replayed=2, semantic_written=1, ranked_out=0, links_decayed=27, utility_faded=16, tags_merged=18 (e.g. drop "python" keep "markdown" @ cosine 1.0 — suspicious: distinct tags at 1.0 smells degenerate)
- Post-sleep probe tag="minisite": EMPTY. Probe tag="atlas-day1": all 3 memories alive (same ids/content). Probe by id: decision retagged [atlas-day1, stdlib, work] (lost minisite/python/markdown/design); lessons reduced to [atlas-day1]. Probe tag="markdown": also empty despite being a merge target.
- Verdict: SURPRISING / WRONG-adjacent. Consolidation kept content (nothing deleted, +1 semantic row) but the tag-merge destroyed my mission's tag rooms — the #minisite room I was told to inspect no longer resolves anything. Tag navigation after sleep is unreliable; content survives under atlas-day1 only. (Also note: I ran sleep twice — second run also reported 2→1; harmless but each sleep rewrites tags again.)

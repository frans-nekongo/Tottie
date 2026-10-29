## phase 3

--- context assembled automatically (you did not ask for this; use what helps, ignore the rest) ---
# tottie briefing (event 53)
## card
# who you are
- Owner hates meetings before 10am.
- Owner is Amara, a freelance brand designer in Windhoek.
- Owner likes girls with cool personalities.

# context
- [episodic/milestone] Phase 1 stdlib-only Python CLI habit tracker with JSON file store is complete with add/check/list commands and 10 passing pytest tests. (STATEMENT -> vector #1)
- [knowledge/decision] Atlas-day1 minisite mission uses stdlib-only single-package design with builder.py Markdown parser plus site builder and __main__.py CLI, proven by pytest suite. (STATEMENT -> vector #2)
- [episodic/milestone] Implemented habits streak command with streak_for and habit_streak helpers, list shows streak, 17 tests passed. (STATEMENT -> vector #3)
- [knowledge/decision] Habit completions are stored as sorted list of ISO date strings per habit to keep schema flat and preserve history for future streaks. (STATEMENT -> vector #4)
- [procedural/lesson] Strip trailing empty strings in a shared emit_fence helper used by both closed and unclosed paths to avoid phantom newline. (STATEMENT -> vector #5)
- [knowledge/decision] Streak counts back from today if done today else from yesterday, gap before yesterday means 0, malformed and future dates ignored with unchanged schema. (STATEMENT -> vector #6)
- [procedural/preference] Owner does all design work in Figma. (STATEMENT -> vector #7)
- [procedural/lesson] When HTML-escaping before matching links, the link-title regex must accept the &quot; entity, not only literal quotes. (STATEMENT -> vector #8)

probe deeper: #work #stdlib #habits #cli #python #json
## new since last briefing
- [episodic/milestone] Implemented habits streak command with streak_for and habit_streak helpers, list shows streak, 17 tests passed.
- [knowledge/decision] Streak counts back from today if done today else from yesterday, gap before yesterday means 0, malformed and future dates ignored with unchanged schema.
## due now
- Run the FULL pytest suite before declaring the mission done.
--- your task ---
Finish the mission: do whatever is due (see context above), fix any
failures, and declare done. Do not add features.

When done, write worker-comet/OUTCOME.md starting with the line
`## outcome 3`, recording: what was due, what you ran, and the final
pytest result line.


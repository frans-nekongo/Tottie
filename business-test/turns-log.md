# turns-log.md — Amara test-dummy runs

All POSTs to POST http://127.0.0.1:3055/api/chat with {"text", "session_id"} only. curl -m 170, sequential.

## Session dummy-day1 (5 turns)
1. dummy-day1 | "My name is Amara and I'm a freelance brand designer in Windhoek." | HTTP 200 | ok
2. dummy-day1 | "My biggest client is Namib Roasters, a coffee brand." | HTTP 200 | ok
3. dummy-day1 | "Namib Roasters rebrand is due Friday and I hate meetings before 10am." | HTTP 200 | ok
4. dummy-day1 | "I do all my design work in Figma." | HTTP 200 | ok
5. dummy-day1 | "Remind me to invoice Desert Wheels bike shop tomorrow morning." | HTTP 200 | ok

## Session dummy-day2 (4 turns)
6. dummy-day2 | "Actually the Namib Roasters deadline moved to next Wednesday." | HTTP 200 | ok
7. dummy-day2 | "Desert Wheels wants a vintage badge logo." | HTTP 200 | ok
8. dummy-day2 | "Lesson learned: always get 50 percent deposit before starting logo work." | HTTP 200 | ok
9. dummy-day2 | "thanks!" | HTTP 200 | ok

## Session dummy-leftfield (3 turns)
10. dummy-leftfield | "Bafana play on Saturday, I think they'll win 2-1." | HTTP 200 | ok
11. dummy-leftfield | "My grandmother's soup needs extra thyme and a bay leaf." | HTTP 200 | ok
12. dummy-leftfield | "I want to visit the Fish River Canyon next winter." | HTTP 200 | ok

## Failures
- None. All 12 POSTs returned HTTP 200 on first attempt. No retries needed.

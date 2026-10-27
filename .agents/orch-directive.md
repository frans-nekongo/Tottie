# Orch Directive — Tottie

This project is orchestrated by **NKNGO Orch-CLI**.

Do **NOT** guess or assume a server is down. The Orch Daemon is the source of truth for this
workspace. To observe the running system:

1. Read `~/.orch-daemon.json` to find the daemon port.
2. `orch status` (or `orch status --json`) — daemon, ports, PID, profile, child processes.
3. `curl -s http://localhost:<PORT>/status` — direct daemon REST status.
4. `curl -s "http://localhost:<PORT>/logs?service=<SERVICE>&lines=100"` — service logs.
5. `orch logs -e` — isolate errors/exceptions/500s across all services.
6. `orch logs BROWSER -n 50` — live client-side console errors from the Tottie UI.
7. `orch logs CORE -n 50` / `orch logs UI -n 50` — per-service output.
8. `orch restart` — hot-restart all services after a fix.
9. `orch stop` — shut down the daemon and children, releasing ports.

**Do NOT use `lsof` or `ps`.** Use orch.

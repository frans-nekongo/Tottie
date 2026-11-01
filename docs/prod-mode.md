# Prod mode: queued writes (async accept)

Since step 3, prod core runs WITHOUT TOTTIE_INLINE_WRITE. Rationale:
measured live, the scribe LLM call is 11.7s of an 11.7s write path
(99.7%), so no code slimming can hit a 2s rows-visible target. Async
accept was chosen over a fast-scribe A/B (deferred): requests return
202 in ~15ms, two queue workers curate in the background, rows land
~12s later.

Start command (from tottie/core):

    ./venv/bin/python -X utf8 -u ./venv/bin/uvicorn app.main:app \
      --host 127.0.0.1 --port 8765 --workers 1 >> /tmp/core.log 2>&1

No TOTTIE_INLINE_WRITE in the environment. Queued mode is also the
code default (config inline_write=False), so tests and fresh boots
agree with prod. Inline mode remains for single-worker debugging.

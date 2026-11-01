"""Bounded write queue + worker pool. Drop-oldest with a counter — the route
never blocks on a slow model. INLINE_WRITE=1 bypasses the queue (single-worker
demo fallback); the route awaits curation directly in that mode.
A turn that dies in a worker is recorded as a DEATH event (turn NULL + cue
set: never collides with the exactly-once index, never pollutes replay) —
the ledger shows the loss instead of swallowing it.
"""
import asyncio
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace

from psycopg.types.json import Json

from .agents import observer, scribe

log = logging.getLogger("tottie.queue")


class Stages:
    """Per-turn stopwatch: named spans in ms, ledged on the event row.
    Shared by the queue worker and the inline route so both paths cost
    the same shape. Optional everywhere (None = don't time)."""

    def __init__(self) -> None:
        self.ms: dict[str, int] = {}

    @contextmanager
    def span(self, name: str):
        t0 = time.monotonic()
        try:
            yield
        finally:
            self.ms[name] = self.ms.get(name, 0) + int(
                (time.monotonic() - t0) * 1000)

    def as_dict(self) -> dict[str, int]:
        return dict(self.ms)


async def curate_turn(*, db, embedder, turn, settings,
                      stages: Stages | None = None) -> str:
    """One turn through observe + persist with stage timing. The single
    curation entry for both the queue worker and the inline route."""
    own = stages is None
    stages = stages or Stages()
    with stages.span("observe"):
        obs = await observer.observe(
            db=db, embedder=embedder, turn=turn, settings=settings,
            stages=stages,
        )
    with stages.span("persist"):
        action = await scribe.persist(
            db=db, embedder=embedder, turn=turn, obs=obs, stages=stages,
        )
    if own:
        log.debug("turn %d stages: %s", turn.turn, stages.as_dict())
    return action


@dataclass(frozen=True)
class WorkerTurn:
    text: str
    session_id: str
    turn: int
    owner: str
    trust: str
    origin: str | None
    client_event_id: str = ""


class WriteQueue:
    def __init__(self, settings, *, db, embedder, maxsize: int = 256, workers: int = 2):
        self._settings = settings
        self._db = db
        self._embedder = embedder
        self._q: asyncio.Queue[WorkerTurn] = asyncio.Queue(maxsize=maxsize)
        self._n_workers = workers
        self._tasks: list[asyncio.Task] = []
        self.dropped = 0

    def enqueue_nowait(self, turn: WorkerTurn) -> str:
        eid = uuid.uuid4().hex
        item = replace(turn, client_event_id=eid)
        try:
            self._q.put_nowait(item)
        except asyncio.QueueFull:
            try:
                self._q.get_nowait()
                self.dropped += 1
                log.warning("write queue full; dropped oldest (total %d)", self.dropped)
            except asyncio.QueueEmpty:
                pass
            self._q.put_nowait(item)
        return eid

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._worker(i)) for i in range(self._n_workers)
        ]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    @property
    def depth(self) -> int:
        return self._q.qsize()

    async def _worker(self, i: int) -> None:
        while True:
            turn = await self._q.get()
            try:
                action = await curate_turn(
                    db=self._db, embedder=self._embedder, turn=turn,
                    settings=self._settings,
                )
                log.info("worker %d curated turn %d: %s", i, turn.turn, action)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("worker %d failed turn %d", i, turn.turn)
                try:
                    await record_death(self._db, turn, e)
                except Exception:
                    log.exception(
                        "worker %d could not record death of turn %d",
                        i, turn.turn,
                    )
            finally:
                self._q.task_done()


async def record_death(db, turn: WorkerTurn, error: Exception) -> None:
    """Ledger the loss: op ERROR with the exception class, turn NULL (never
    collides with exactly-once) and cue set (replay/brief skip it)."""
    await db.execute(
        "INSERT INTO memory_events (owner, session_id, turn, utterance, "
        "observer_verdict, scribe_action, cue, latency_ms, tokens) "
        "VALUES (%s,%s,NULL,%s,%s,%s,%s,0,0)",
        (
            turn.owner, turn.session_id, turn.text,
            Json({"keep": False, "reason": "worker died curating this turn"}),
            Json({"op": "ERROR", "turn": turn.turn,
                  "error": f"{type(error).__name__}: {str(error)[:200]}"}),
            Json({"type": "DEATH"}),
        ),
    )

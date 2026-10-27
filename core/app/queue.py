"""Bounded write queue + worker pool. Drop-oldest with a counter — the route
never blocks on a slow model. INLINE_WRITE=1 bypasses the queue (single-worker
demo fallback); the route awaits curation directly in that mode.
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass, replace

from .agents import observer, scribe

log = logging.getLogger("tottie.queue")


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
                obs = await observer.observe(
                    db=self._db, embedder=self._embedder, turn=turn,
                    settings=self._settings,
                )
                action = await scribe.persist(
                    db=self._db, embedder=self._embedder, turn=turn, obs=obs
                )
                log.info("worker %d curated turn %d: %s", i, turn.turn, action)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("worker %d failed turn %d", i, turn.turn)
            finally:
                self._q.task_done()

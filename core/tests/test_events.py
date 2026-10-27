"""SSE via direct ASGI invocation — real routing, auth, framing, DB, resume.

Why not httpx: ASGITransport (httpx 0.28.1, verified by source + probe)
awaits the ENTIRE app call and buffers the body before returning, so an
infinite SSE stream can never deliver a byte through it — the old test hung
forever on a route that works. Here the test IS the server: it drives the
real app callable with manual send/receive queues and asserts on the raw
SSE bytes. Nothing is mocked.
"""
import asyncio
import json

import pytest
from psycopg.types.json import Json


def _scope(query: str) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/events",
        "raw_path": b"/events",
        "query_string": query.encode(),
        "headers": [(b"host", b"test")],
        "server": ("test", 80),
        "client": ("127.0.0.1", 123),
        "root_path": "",
    }


class Stream:
    """One open SSE connection against the live app."""

    def __init__(self, app, query: str) -> None:
        self._app = app
        self._query = query
        self.chunks: asyncio.Queue = asyncio.Queue()
        self._hangup = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.status: int | None = None
        self._buf = b""

    async def __aenter__(self) -> "Stream":
        async def receive():
            await self._hangup.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            await self.chunks.put(message)

        self._task = asyncio.create_task(
            self._app(_scope(self._query), receive, send)
        )
        msg = await asyncio.wait_for(self.chunks.get(), timeout=10)
        assert msg["type"] == "http.response.start", msg
        self.status = msg["status"]
        return self

    async def __aexit__(self, *exc) -> None:
        self._hangup.set()  # client hangs up: the stream must end, not leak
        try:
            await asyncio.wait_for(self._task, timeout=10)
        except asyncio.TimeoutError:
            self._task.cancel()
            raise AssertionError("stream did not end after disconnect")

    async def next_frame(self, timeout: float = 10) -> dict | None:
        """Next complete SSE frame as {id, event, data}, or None on quiet."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            if b"\r\n\r\n" in self._buf or b"\n\n" in self._buf:
                raw, _, self._buf = self._buf.replace(b"\r\n", b"\n").partition(b"\n\n")
                frame: dict = {}
                for line in raw.decode().split("\n"):
                    if line.startswith("data:"):
                        frame["data"] = json.loads(line[5:].strip())
                    elif line.startswith("id:"):
                        frame["id"] = int(line[3:].strip())
                    elif line.startswith("event:"):
                        frame["event"] = line[6:].strip()
                if "data" in frame:
                    return frame
                continue  # comment/ping frame: keep waiting inside the budget
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return None
            try:
                msg = await asyncio.wait_for(self.chunks.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            assert msg["type"] == "http.response.body", msg
            self._buf += msg.get("body", b"")
            if not msg.get("more_body", False):
                return None


async def _seed(db, session_id: str, utterance: str = "seeded") -> None:
    await db.execute(
        "INSERT INTO memory_events (session_id, turn, utterance, observer_verdict,"
        " scribe_action, latency_ms, tokens) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (session_id, 0, utterance, Json({"keep": True}), Json({"op": "NEW"}), 5, 10),
    )


@pytest.mark.asyncio
async def test_events_stream_and_resume(booted_app, db):
    await _seed(db, "sse")
    async with Stream(booted_app, "session_id=sse&token=test-token") as s:
        assert s.status == 200
        frame = await s.next_frame()
        assert frame is not None, "seed row never streamed"
        assert frame["event"] == "memory"
        assert frame["data"]["utterance"] == "seeded"
        assert frame["data"]["action"]["op"] == "NEW"
        first_id = frame["id"]
    # resume past it: quiet until genuinely new data lands (live tail proof)
    async with Stream(
        booted_app, f"session_id=sse&last_event_id={first_id}&token=test-token"
    ) as s:
        assert s.status == 200
        assert await s.next_frame(timeout=2) is None, "replayed known event"
        await _seed(db, "sse", utterance="second")
        frame = await s.next_frame()
        assert frame is not None, "live tail missed the new row"
        assert frame["data"]["utterance"] == "second"
        assert frame["id"] > first_id


@pytest.mark.asyncio
async def test_events_401(client):
    r = await client.get("/events?session_id=sse&token=wrong")
    assert r.status_code == 401
    r = await client.get("/events?session_id=sse")
    assert r.status_code == 401

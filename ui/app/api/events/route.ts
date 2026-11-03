import { coreUrl } from "../core";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// SSE passthrough: the browser holds no token; this route injects it.
// Core /events authenticates via ?token= (EventSource cannot set headers).
// Chunks are pumped explicitly with an immediate `: connected` flush:
// passing upstream.body through untouched never flushes headers on an
// idle stream (verified live: 0 bytes until first chunk).
export async function GET(req: Request): Promise<Response> {
  const { searchParams } = new URL(req.url);
  searchParams.set("token", process.env.TOTTIE_API_TOKEN ?? "");
  // Gapless resume: EventSource auto-sends Last-Event-ID on reconnect;
  // forward it as the query cursor or every reconnect replays the backlog.
  const resume = req.headers.get("last-event-id");
  if (resume && !searchParams.has("last_event_id")) {
    searchParams.set("last_event_id", resume);
  }
  const upstream = await fetch(`${coreUrl("/events")}?${searchParams.toString()}`, {
    headers: { Accept: "text/event-stream" },
    cache: "no-store",
  });
  if (!upstream.ok || !upstream.body) {
    return Response.json(
      { error: `core events: ${upstream.status}` }, { status: upstream.status }
    );
  }
  const reader = upstream.body.getReader();
  const enc = new TextEncoder();
  const stream = new ReadableStream({
    async start(c) {
      c.enqueue(enc.encode(": connected\n\n"));
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          c.enqueue(value);
        }
      } catch {
        /* upstream closed */
      }
      try {
        c.close();
      } catch {
        /* client went away */
      }
    },
    cancel() {
      reader.cancel().catch(() => {});
    },
  });
  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}

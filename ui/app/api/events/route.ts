import { coreUrl } from "../core";

// SSE passthrough: the browser holds no token; this route injects it.
// Core /events authenticates via ?token= (EventSource cannot set headers).
export async function GET(req: Request): Promise<Response> {
  const { searchParams } = new URL(req.url);
  searchParams.set("token", process.env.TOTTIE_API_TOKEN ?? "");
  const upstream = await fetch(`${coreUrl("/events")}?${searchParams.toString()}`, {
    headers: { Accept: "text/event-stream" },
  });
  if (!upstream.ok || !upstream.body) {
    return Response.json(
      { error: `core events: ${upstream.status}` }, { status: upstream.status }
    );
  }
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}

import { OWNER, authHeaders, coreUrl } from "../core";

export const dynamic = "force-dynamic";

// Bluetooth board: which agents are visible, which are paired. Presence
// is liveness data — never cache it (see /api/graph for the stale lie).
export async function GET(req: Request): Promise<Response> {
  const { searchParams } = new URL(req.url);
  if (!searchParams.has("owner")) searchParams.set("owner", OWNER);
  const r = await fetch(`${coreUrl("/agents")}?${searchParams.toString()}`, {
    headers: authHeaders(),
    cache: "no-store",
  });
  return Response.json(await r.json(), { status: r.status });
}

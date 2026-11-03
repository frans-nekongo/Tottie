import { OWNER, authHeaders, coreUrl } from "../core";

export const dynamic = "force-dynamic";

// The brain refetches this on every memory event: any cache (Full Route
// Cache or the server-fetch Data Cache) freezes the graph until a browser
// reload revalidates — the "have to refresh" lie. Never cache it.
export async function GET(req: Request): Promise<Response> {
  const { searchParams } = new URL(req.url);
  if (!searchParams.has("owner")) searchParams.set("owner", OWNER);
  const r = await fetch(`${coreUrl("/graph")}?${searchParams.toString()}`, {
    headers: authHeaders(),
    cache: "no-store",
  });
  return Response.json(await r.json(), { status: r.status });
}

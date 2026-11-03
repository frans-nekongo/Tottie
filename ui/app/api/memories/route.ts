import { OWNER, authHeaders, coreUrl } from "../core";

export const dynamic = "force-dynamic";

// Row browser for the pending strip. Never cache (see /api/graph).
export async function GET(req: Request): Promise<Response> {
  const { searchParams } = new URL(req.url);
  if (!searchParams.has("owner")) searchParams.set("owner", OWNER);
  const r = await fetch(`${coreUrl("/memories")}?${searchParams.toString()}`, {
    headers: authHeaders(),
    cache: "no-store",
  });
  return Response.json(await r.json(), { status: r.status });
}

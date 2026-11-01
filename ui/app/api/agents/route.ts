import { OWNER, authHeaders, coreUrl } from "../core";

// Bluetooth board: which agents are visible, which are paired.
export async function GET(req: Request): Promise<Response> {
  const { searchParams } = new URL(req.url);
  if (!searchParams.has("owner")) searchParams.set("owner", OWNER);
  const r = await fetch(`${coreUrl("/agents")}?${searchParams.toString()}`, {
    headers: authHeaders(),
  });
  return Response.json(await r.json(), { status: r.status });
}

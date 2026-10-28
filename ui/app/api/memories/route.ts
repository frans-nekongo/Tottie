import { OWNER, authHeaders, coreUrl } from "../core";

export async function GET(req: Request): Promise<Response> {
  const { searchParams } = new URL(req.url);
  if (!searchParams.has("owner")) searchParams.set("owner", OWNER);
  const r = await fetch(`${coreUrl("/memories")}?${searchParams.toString()}`, {
    headers: authHeaders(),
  });
  return Response.json(await r.json(), { status: r.status });
}

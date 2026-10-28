import { OWNER, authHeaders, coreUrl } from "../core";

export async function POST(req: Request): Promise<Response> {
  const body = await req.json();
  const r = await fetch(coreUrl("/consolidate"), {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ owner: OWNER, ...body }),
  });
  return Response.json(await r.json(), { status: r.status });
}

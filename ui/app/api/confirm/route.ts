import { OWNER, authHeaders, coreUrl } from "../core";

export async function POST(req: Request): Promise<Response> {
  const { id } = await req.json();
  const r = await fetch(coreUrl(`/memories/${id}/confirm`), {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ owner: OWNER }),
  });
  return Response.json(await r.json(), { status: r.status });
}

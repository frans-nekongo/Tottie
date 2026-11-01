import { authHeaders, coreUrl } from "../../core";

export async function POST(req: Request): Promise<Response> {
  const body = await req.json();
  const r = await fetch(coreUrl("/agents/pair"), {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  return Response.json(await r.json(), { status: r.status });
}

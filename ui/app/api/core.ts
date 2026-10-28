// Server-side core client: the Bearer [REDACTED] never reaches the browser.
const CORE = process.env.TOTTIE_CORE_URL ?? "http://127.0.0.1:8765";
const TOKEN = process.env.TOTTIE_API_TOKEN ?? "";
export const OWNER = process.env.TOTTIE_OWNER ?? "owner_local";

export function coreUrl(path: string): string {
  return `${CORE}${path}`;
}

export function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" };
}

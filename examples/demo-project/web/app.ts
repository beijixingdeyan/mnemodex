// Minimal TypeScript client for the demo auth service, fetch-only.

const API = "http://127.0.0.1:7331";

export interface Session {
  token: string;
  username: string;
  issuedAt: number; // epoch ms; server drops tokens after 60s
}

export async function login(username: string): Promise<Session> {
  const res = await fetch(`${API}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status}`);
  const token = (await res.json()) as string;
  return { token, username, issuedAt: Date.now() };
}

// Mirrors the server-side 60s TTL (TokenCache.ttl_seconds in service/).
export function isExpired(session: Session): boolean {
  return Date.now() - session.issuedAt > 60_000;
}
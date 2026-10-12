export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Health = { status: string; postgis: string };

export async function getHealth(): Promise<Health> {
  const resp = await fetch(`${API_URL}/health`);
  if (!resp.ok) throw new Error(`API health check failed: ${resp.status}`);
  return resp.json();
}

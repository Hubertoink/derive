import { NextResponse } from "next/server";

export async function POST(request: Request) {
  let body: { identifier?: string; password?: string; next?: string };
  try {
    body = await request.json() as { identifier?: string; password?: string; next?: string };
  } catch {
    return NextResponse.json({ detail: "Ungültige Anmeldedaten." }, { status: 400 });
  }

  const apiUrl = process.env.CURATOR_API_URL ?? "http://localhost:8000";
  const upstream = await fetch(`${apiUrl}/api/v1/auth/login`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: body.identifier, password: body.password }),
  });
  const payload = await upstream.json().catch(() => ({})) as { detail?: string };
  if (!upstream.ok) return NextResponse.json(payload, { status: upstream.status });

  const response = NextResponse.json({ ok: true, next: body.next?.startsWith("/") ? body.next : "/" });
  const cookie = upstream.headers.get("set-cookie");
  if (cookie) response.headers.set("set-cookie", cookie);
  return response;
}

import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body) return NextResponse.json({ detail: "Ungültige Registrierungsdaten." }, { status: 400 });

  const apiUrl = process.env.CURATOR_API_URL ?? "http://localhost:8000";
  const upstream = await fetch(`${apiUrl}/api/v1/auth/register`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await upstream.json().catch(() => ({}));
  if (!upstream.ok) return NextResponse.json(payload, { status: upstream.status });
  const response = NextResponse.json({ ok: true });
  const cookie = upstream.headers.get("set-cookie");
  if (cookie) response.headers.set("set-cookie", cookie);
  return response;
}

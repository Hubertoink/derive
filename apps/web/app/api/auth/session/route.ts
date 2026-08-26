import { NextResponse } from "next/server";

export async function GET(request: Request) {
  const apiUrl = process.env.CURATOR_API_URL ?? "http://localhost:8000";
  const upstream = await fetch(`${apiUrl}/api/v1/auth/session`, {
    cache: "no-store",
    headers: { cookie: request.headers.get("cookie") ?? "" },
  });
  const payload = await upstream.json().catch(() => ({}));
  return NextResponse.json(payload, { status: upstream.status });
}

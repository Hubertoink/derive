import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const apiUrl = process.env.CURATOR_API_URL ?? "http://localhost:8000";
  const upstream = await fetch(`${apiUrl}/api/v1/auth/logout`, {
    method: "POST",
    cache: "no-store",
    headers: { cookie: request.headers.get("cookie") ?? "" },
  });
  const response = NextResponse.json({ ok: upstream.ok }, { status: upstream.ok ? 200 : upstream.status });
  const cookie = upstream.headers.get("set-cookie");
  if (cookie) response.headers.set("set-cookie", cookie);
  return response;
}

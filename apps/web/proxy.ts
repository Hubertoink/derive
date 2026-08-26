import { NextRequest, NextResponse } from "next/server";
import { COOKIE_NAME } from "./lib/auth";

export async function proxy(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  if (pathname === "/login" || pathname === "/registrieren" || pathname.startsWith("/api/auth/") || pathname === "/health") return NextResponse.next();
  const token = request.cookies.get(COOKIE_NAME)?.value;
  if (token) {
    try {
      const apiUrl = process.env.CURATOR_API_URL ?? "http://localhost:8000";
      const session = await fetch(`${apiUrl}/api/v1/auth/session`, {
        cache: "no-store",
        headers: { "X-Derive-Session": token },
      });
      if (session.ok) return NextResponse.next();
    } catch {
      // Fail closed below. Protected pages must not render with an invalid
      // session while the API is unavailable or still starting.
    }
  }
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.searchParams.set("next", `${pathname}${request.nextUrl.search}`);
  if (token) loginUrl.searchParams.set("expired", "1");
  const response = NextResponse.redirect(loginUrl);
  response.cookies.delete(COOKIE_NAME);
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|health|brand/|images/).*)"],
};

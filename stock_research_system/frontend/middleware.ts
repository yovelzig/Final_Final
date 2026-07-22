import { NextResponse, type NextRequest } from "next/server";

import { REFRESH_COOKIE_NAME } from "@/lib/auth/cookies";
import { sanitizeReturnPath } from "@/lib/auth/return-path";

/**
 * Navigation-level route protection ONLY - this checks for the
 * *presence* of the refresh cookie, never its validity (the cookie is
 * HttpOnly and opaque; middleware cannot and does not decode or verify
 * it). This is a UX optimization to avoid a flash of protected content
 * before `AuthProvider` bootstraps, NOT the real authorization
 * boundary - the FastAPI backend independently authorizes every
 * `/api/v1/*` call regardless of what this middleware decides, and a
 * present-but-expired/revoked cookie still correctly fails at
 * `POST /api/auth/session` (which clears it) and every subsequent API
 * call (which gets a real 401).
 */

const PROTECTED_PREFIXES = [
  "/dashboard",
  "/learn",
  "/lessons",
  "/practice",
  "/diagnostic",
  "/scenarios",
  "/portfolios",
  "/tutor",
  "/settings",
];

const AUTH_PAGES = ["/login", "/register"];

function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

function isAuthPage(pathname: string): boolean {
  return AUTH_PAGES.includes(pathname);
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const hasRefreshCookie = request.cookies.has(REFRESH_COOKIE_NAME);

  if (isProtectedPath(pathname) && !hasRefreshCookie) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("returnTo", `${pathname}${search}`);
    return NextResponse.redirect(loginUrl);
  }

  if (isAuthPage(pathname) && hasRefreshCookie) {
    const returnTo = sanitizeReturnPath(request.nextUrl.searchParams.get("returnTo"));
    return NextResponse.redirect(new URL(returnTo, request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/learn/:path*",
    "/lessons/:path*",
    "/practice/:path*",
    "/diagnostic/:path*",
    "/scenarios/:path*",
    "/portfolios/:path*",
    "/tutor/:path*",
    "/settings/:path*",
    "/login",
    "/register",
  ],
};

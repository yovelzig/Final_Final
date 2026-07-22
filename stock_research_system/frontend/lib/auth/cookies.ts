import type { NextResponse } from "next/server";

import { getServerEnv } from "@/lib/environment";

/** Server-only. Never import from a Client Component. */
export const REFRESH_COOKIE_NAME = "finquest_refresh_token";

// Matches the backend's default AUTH_REFRESH_TOKEN_DAYS (30) - the
// cookie's own Max-Age is a client-side courtesy bound, not the source
// of truth for token validity (the backend independently expires and
// can revoke the token server-side regardless of what the cookie says).
const REFRESH_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

export function setRefreshCookie(response: NextResponse, refreshToken: string): void {
  const { AUTH_COOKIE_SECURE } = getServerEnv();
  response.cookies.set(REFRESH_COOKIE_NAME, refreshToken, {
    httpOnly: true,
    secure: AUTH_COOKIE_SECURE,
    sameSite: "strict",
    path: "/",
    maxAge: REFRESH_COOKIE_MAX_AGE_SECONDS,
  });
}

export function clearRefreshCookie(response: NextResponse): void {
  const { AUTH_COOKIE_SECURE } = getServerEnv();
  response.cookies.set(REFRESH_COOKIE_NAME, "", {
    httpOnly: true,
    secure: AUTH_COOKIE_SECURE,
    sameSite: "strict",
    path: "/",
    maxAge: 0,
  });
}

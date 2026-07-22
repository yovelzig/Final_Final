import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { apiInternalBaseUrl } from "@/lib/environment";
import { clearRefreshCookie, REFRESH_COOKIE_NAME } from "@/lib/auth/cookies";
import { isTrustedOrigin, originRejectedResponse } from "@/lib/auth/origin";

/**
 * Idempotent by design: whether or not a refresh cookie is present,
 * whether or not the backend call succeeds, the cookie is always
 * cleared and this always returns 200 - a client can call this
 * speculatively without checking auth state first.
 */
export async function POST(request: Request): Promise<Response> {
  if (!isTrustedOrigin(request)) {
    return originRejectedResponse();
  }

  const cookieStore = await cookies();
  const refreshToken = cookieStore.get(REFRESH_COOKIE_NAME)?.value;

  if (refreshToken) {
    try {
      await fetch(`${apiInternalBaseUrl()}/api/v1/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: "no-store",
      });
    } catch {
      // Backend unreachable or already-invalid token - the cookie is
      // cleared below regardless, so the browser's session ends either way.
    }
  }

  const response = NextResponse.json({ loggedOut: true }, { status: 200 });
  clearRefreshCookie(response);
  return response;
}

import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { callBackend, FinQuestApiError } from "@/lib/auth/backend";
import { clearRefreshCookie, REFRESH_COOKIE_NAME, setRefreshCookie } from "@/lib/auth/cookies";
import { isTrustedOrigin, originRejectedResponse } from "@/lib/auth/origin";
import type { MeResponse, TokenPairResponse } from "@/types/api-schemas";
import type { NoSessionPayload } from "@/types/session";

/**
 * Shared implementation behind both `POST /api/auth/session` (the
 * documented session-bootstrap endpoint) and `POST /api/auth/refresh`
 * (a same-behavior alias, so the endpoint exists under either name) -
 * reads the HttpOnly refresh cookie, rotates it against the real
 * backend, and returns a fresh access token plus the current identity.
 * Never returns the raw refresh token in the JSON body.
 */
export async function handleSessionBootstrap(request: Request): Promise<Response> {
  if (!isTrustedOrigin(request)) {
    return originRejectedResponse();
  }

  const cookieStore = await cookies();
  const refreshToken = cookieStore.get(REFRESH_COOKIE_NAME)?.value;

  if (!refreshToken) {
    return NextResponse.json({ authenticated: false } satisfies NoSessionPayload, { status: 200 });
  }

  try {
    const tokens = await callBackend<TokenPairResponse>("/api/v1/auth/refresh", {
      method: "POST",
      body: { refresh_token: refreshToken },
    });

    const me = await callBackend<MeResponse>("/api/v1/auth/me", {
      method: "GET",
      accessToken: tokens.access_token,
    });

    const response = NextResponse.json(
      {
        authenticated: true,
        accessToken: tokens.access_token,
        accessTokenExpiresAt: tokens.access_token_expires_at,
        account: me.account,
        learner: me.learner,
      },
      { status: 200 }
    );
    setRefreshCookie(response, tokens.refresh_token);
    return response;
  } catch (error) {
    // An invalid/expired/reused/revoked refresh token means there is no
    // session - clear the now-useless cookie rather than leaving it to
    // fail the same way on every subsequent request.
    if (error instanceof FinQuestApiError && error.status === 401) {
      const response = NextResponse.json({ authenticated: false } satisfies NoSessionPayload, { status: 200 });
      clearRefreshCookie(response);
      return response;
    }
    throw error;
  }
}

import { NextResponse } from "next/server";

import { apiErrorResponse, callBackend, FinQuestApiError, invalidRequestBodyResponse } from "@/lib/auth/backend";
import { setRefreshCookie } from "@/lib/auth/cookies";
import { isTrustedOrigin, originRejectedResponse } from "@/lib/auth/origin";
import type { LoginRequest, LoginResponse, MeResponse } from "@/types/api-schemas";

export async function POST(request: Request): Promise<Response> {
  if (!isTrustedOrigin(request)) {
    return originRejectedResponse();
  }

  let payload: LoginRequest;
  try {
    payload = (await request.json()) as LoginRequest;
  } catch {
    return invalidRequestBodyResponse();
  }

  try {
    const result = await callBackend<LoginResponse>("/api/v1/auth/login", { method: "POST", body: payload });
    const me = await callBackend<MeResponse>("/api/v1/auth/me", {
      method: "GET",
      accessToken: result.tokens.access_token,
    });

    const response = NextResponse.json(
      {
        accessToken: result.tokens.access_token,
        accessTokenExpiresAt: result.tokens.access_token_expires_at,
        account: result.account,
        learner: me.learner,
      },
      { status: 200 }
    );
    // The raw refresh token is set as an HttpOnly cookie here and only
    // here in this response - it is never included in the JSON body
    // above, so no browser-executed JavaScript can ever read it.
    setRefreshCookie(response, result.tokens.refresh_token);
    return response;
  } catch (error) {
    if (error instanceof FinQuestApiError) {
      return apiErrorResponse(error);
    }
    throw error;
  }
}

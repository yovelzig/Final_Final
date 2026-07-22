import { NextResponse } from "next/server";

import { apiErrorResponse, callBackend, FinQuestApiError, invalidRequestBodyResponse } from "@/lib/auth/backend";
import { setRefreshCookie } from "@/lib/auth/cookies";
import { isTrustedOrigin, originRejectedResponse } from "@/lib/auth/origin";
import type { RegisterRequest, RegisterResponse } from "@/types/api-schemas";

export async function POST(request: Request): Promise<Response> {
  if (!isTrustedOrigin(request)) {
    return originRejectedResponse();
  }

  let payload: RegisterRequest;
  try {
    payload = (await request.json()) as RegisterRequest;
  } catch {
    return invalidRequestBodyResponse();
  }

  try {
    const result = await callBackend<RegisterResponse>("/api/v1/auth/register", { method: "POST", body: payload });

    const response = NextResponse.json(
      {
        accessToken: result.tokens.access_token,
        accessTokenExpiresAt: result.tokens.access_token_expires_at,
        account: result.account,
        learner: result.learner,
      },
      { status: 201 }
    );
    setRefreshCookie(response, result.tokens.refresh_token);
    return response;
  } catch (error) {
    if (error instanceof FinQuestApiError) {
      return apiErrorResponse(error);
    }
    throw error;
  }
}

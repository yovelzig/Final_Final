import type { components } from "@/types/generated-api";

export type PublicAccount = components["schemas"]["PublicAccount"];
export type PublicLearner = components["schemas"]["PublicLearner"];

/**
 * The shape returned by this frontend's OWN `/api/auth/*` Route
 * Handlers - deliberately distinct from the backend's `LoginResponse`/
 * `RegisterResponse`/`TokenPairResponse`: it NEVER includes a refresh
 * token (that only ever exists as the HttpOnly cookie, never in a JSON
 * body a browser script could read).
 */
export interface SessionPayload {
  accessToken: string;
  accessTokenExpiresAt: string;
  account: PublicAccount;
  learner: PublicLearner | null;
}

export interface NoSessionPayload {
  authenticated: false;
}

export type SessionBootstrapResult = ({ authenticated: true } & SessionPayload) | NoSessionPayload;

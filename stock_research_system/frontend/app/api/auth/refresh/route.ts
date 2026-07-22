import { handleSessionBootstrap } from "@/lib/auth/session-handler";

/**
 * Same-behavior alias for `POST /api/auth/session` (rotates the refresh
 * cookie and returns a fresh access token + identity) - this is the
 * endpoint the browser-side single-flight refresh logic in
 * `lib/api/client.ts` actually calls on a 401.
 */
export async function POST(request: Request): Promise<Response> {
  return handleSessionBootstrap(request);
}

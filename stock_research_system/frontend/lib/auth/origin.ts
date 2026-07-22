import { getServerEnv } from "@/lib/environment";

/**
 * Defense-in-depth CSRF protection for the cookie-setting auth Route
 * Handlers, on top of (not instead of) the refresh cookie's own
 * `SameSite=Strict` attribute: rejects any mutation request whose
 * `Origin` (falling back to `Host` when `Origin` is absent, e.g. some
 * same-origin browser requests) doesn't match the configured frontend
 * origin exactly.
 */
export function isTrustedOrigin(request: Request): boolean {
  const { FINQUEST_WEB_ORIGIN } = getServerEnv();
  const origin = request.headers.get("origin");
  if (origin !== null) {
    return origin === FINQUEST_WEB_ORIGIN;
  }

  // No Origin header (some legitimate same-origin requests omit it) -
  // fall back to comparing Host against the configured origin's host.
  const host = request.headers.get("host");
  if (host === null) {
    return false;
  }
  try {
    const expectedHost = new URL(FINQUEST_WEB_ORIGIN).host;
    return host === expectedHost;
  } catch {
    return false;
  }
}

export function originRejectedResponse(): Response {
  return Response.json(
    { error: { code: "UNTRUSTED_ORIGIN", message: "This request's origin is not allowed.", details: [], correlation_id: "n/a" } },
    { status: 403 }
  );
}

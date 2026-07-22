import { http, HttpResponse } from "msw";

/** Default handlers active for every test. `AuthProvider` always calls
 * `POST /api/auth/session` on mount to bootstrap - without a default
 * handler, any test that renders it (even indirectly, via
 * `AppProviders`) would hang on a real network call. Individual tests
 * override this with `server.use(...)` for authenticated scenarios. */
export const handlers = [
  http.post("/api/auth/session", () => HttpResponse.json({ authenticated: false })),
];

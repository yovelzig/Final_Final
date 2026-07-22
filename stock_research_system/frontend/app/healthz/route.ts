/** Lightweight liveness check for the frontend container - never calls
 * the backend (that's the `/health` and `/ready` endpoints' job). Used
 * by the Dockerfile's HEALTHCHECK and by orchestration readiness probes. */
export function GET(): Response {
  return Response.json({ status: "ok", service: "finquest-web" }, { status: 200 });
}

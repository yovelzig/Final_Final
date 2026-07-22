import { z } from "zod";

/**
 * Validated environment configuration, split into browser-safe and
 * server-only pieces. Never import `serverEnv` from a Client Component
 * - `serverEnv` fields are only ever read inside Route Handlers,
 * Server Components, and `middleware.ts`.
 *
 * Fails fast (throws at module load, i.e. at server startup or first
 * client bundle evaluation) with a clear message listing every missing
 * or invalid variable, rather than surfacing a confusing runtime error
 * deep inside a fetch call.
 */

const browserEnvSchema = z.object({
  NEXT_PUBLIC_FINQUEST_API_BASE_URL: z.string().url(),
  NEXT_PUBLIC_APP_NAME: z.string().min(1).default("FinQuest"),
});

const serverEnvSchema = z.object({
  FINQUEST_API_INTERNAL_URL: z.string().url().optional(),
  FINQUEST_WEB_ORIGIN: z.string().url(),
  AUTH_COOKIE_SECURE: z
    .string()
    .optional()
    .transform((value) => value === "true")
    .default("false"),
});

function formatZodError(prefix: string, error: z.ZodError): string {
  const issues = error.issues
    .map((issue) => `  - ${issue.path.join(".")}: ${issue.message}`)
    .join("\n");
  return `${prefix}\n${issues}`;
}

function loadBrowserEnv() {
  const result = browserEnvSchema.safeParse({
    NEXT_PUBLIC_FINQUEST_API_BASE_URL: process.env.NEXT_PUBLIC_FINQUEST_API_BASE_URL,
    NEXT_PUBLIC_APP_NAME: process.env.NEXT_PUBLIC_APP_NAME,
  });
  if (!result.success) {
    throw new Error(formatZodError("Invalid or missing browser-safe environment variables:", result.error));
  }
  return result.data;
}

function loadServerEnv() {
  const result = serverEnvSchema.safeParse({
    FINQUEST_API_INTERNAL_URL: process.env.FINQUEST_API_INTERNAL_URL,
    FINQUEST_WEB_ORIGIN: process.env.FINQUEST_WEB_ORIGIN,
    AUTH_COOKIE_SECURE: process.env.AUTH_COOKIE_SECURE,
  });
  if (!result.success) {
    throw new Error(formatZodError("Invalid or missing server-only environment variables:", result.error));
  }
  return result.data;
}

export const browserEnv = loadBrowserEnv();

/**
 * Only call this from server-side code (Route Handlers, Server
 * Components, `middleware.ts`). Calling it from a Client Component
 * would still only see whatever Next.js actually inlined (nothing,
 * for non-`NEXT_PUBLIC_` variables) - but the lazy-getter shape here
 * makes that mistake fail loudly instead of silently returning
 * `undefined` fields.
 */
export function getServerEnv() {
  return loadServerEnv();
}

/** The URL the Next.js *server* uses to reach FastAPI - prefers the
 * internal (e.g. in-Docker-network) URL, falling back to the public one
 * for local dev without Docker. */
export function apiInternalBaseUrl(): string {
  const server = getServerEnv();
  return server.FINQUEST_API_INTERNAL_URL ?? browserEnv.NEXT_PUBLIC_FINQUEST_API_BASE_URL;
}

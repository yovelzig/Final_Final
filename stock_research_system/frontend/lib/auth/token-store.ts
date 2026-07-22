"use client";

/**
 * The ONLY place the access token lives: a module-level variable in
 * browser memory. Never written to `localStorage`/`sessionStorage`/
 * `IndexedDB`/a cookie - a full page reload always starts from
 * `authenticated: false` until `AuthProvider` re-bootstraps the
 * session via `POST /api/auth/session` (which itself only ever reads
 * the HttpOnly refresh cookie, never JavaScript-visible storage).
 *
 * `lib/api/client.ts` (a plain module, not a React component) reads
 * and writes this synchronously so it can attach the current token to
 * every request and update it after a single-flight refresh, without
 * needing to be a React hook itself. `providers/AuthProvider.tsx`
 * subscribes via `useSyncExternalStore` to reflect the same value
 * reactively for components.
 */
export interface AccessTokenState {
  accessToken: string;
  accessTokenExpiresAt: string;
}

let currentToken: AccessTokenState | null = null;
const listeners = new Set<() => void>();

export function getAccessTokenSnapshot(): AccessTokenState | null {
  return currentToken;
}

export function setAccessToken(token: AccessTokenState | null): void {
  currentToken = token;
  for (const listener of listeners) listener();
}

export function subscribeToAccessToken(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

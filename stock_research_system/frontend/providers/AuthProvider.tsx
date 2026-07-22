"use client";

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";

import { apiClient, FinQuestApiError } from "@/lib/api/client";
import { getAccessTokenSnapshot, setAccessToken, subscribeToAccessToken } from "@/lib/auth/token-store";
import type { LogoutAllResponse } from "@/types/api-schemas";
import type { PublicAccount, PublicLearner } from "@/types/session";

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

export interface AuthContextValue {
  status: AuthStatus;
  account: PublicAccount | null;
  learner: PublicLearner | null;
  accessToken: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (params: {
    email: string;
    password: string;
    displayName: string;
    dailyGoalMinutes: number;
  }) => Promise<void>;
  logout: () => Promise<void>;
  logoutAll: () => Promise<number>;
  /** Re-reads the current identity (e.g. after a settings change) without a full page reload. */
  refreshIdentity: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

interface SessionBootstrapPayload {
  authenticated: boolean;
  accessToken?: string;
  accessTokenExpiresAt?: string;
  account?: PublicAccount;
  learner?: PublicLearner | null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const tokenState = useSyncExternalStore(subscribeToAccessToken, getAccessTokenSnapshot, () => null);
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [account, setAccount] = useState<PublicAccount | null>(null);
  const [learner, setLearner] = useState<PublicLearner | null>(null);

  const applySession = useCallback((payload: SessionBootstrapPayload) => {
    if (payload.authenticated && payload.accessToken && payload.accessTokenExpiresAt && payload.account) {
      setAccessToken({ accessToken: payload.accessToken, accessTokenExpiresAt: payload.accessTokenExpiresAt });
      setAccount(payload.account);
      setLearner(payload.learner ?? null);
      setStatus("authenticated");
    } else {
      setAccessToken(null);
      setAccount(null);
      setLearner(null);
      setStatus("unauthenticated");
    }
  }, []);

  const bootstrap = useCallback(async () => {
    try {
      const response = await fetch("/api/auth/session", { method: "POST", credentials: "same-origin" });
      const body = (await response.json()) as SessionBootstrapPayload;
      applySession(body);
    } catch {
      applySession({ authenticated: false });
    }
  }, [applySession]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  const login = useCallback(
    async (email: string, password: string) => {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const body = (await response.json()) as SessionBootstrapPayload & { error?: { code: string; message: string } };
      if (!response.ok) {
        throw new FinQuestApiError({
          status: response.status,
          code: body.error?.code ?? "UNKNOWN_ERROR",
          message: body.error?.message ?? "Login failed.",
        });
      }
      applySession({ ...body, authenticated: true });
    },
    [applySession]
  );

  const register = useCallback(
    async (params: { email: string; password: string; displayName: string; dailyGoalMinutes: number }) => {
      const response = await fetch("/api/auth/register", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: params.email,
          password: params.password,
          display_name: params.displayName,
          daily_goal_minutes: params.dailyGoalMinutes,
        }),
      });
      const body = (await response.json()) as SessionBootstrapPayload & { error?: { code: string; message: string } };
      if (!response.ok) {
        throw new FinQuestApiError({
          status: response.status,
          code: body.error?.code ?? "UNKNOWN_ERROR",
          message: body.error?.message ?? "Registration failed.",
        });
      }
      applySession({ ...body, authenticated: true });
    },
    [applySession]
  );

  const logout = useCallback(async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      applySession({ authenticated: false });
      queryClient.clear();
    }
  }, [applySession, queryClient]);

  const logoutAll = useCallback(async () => {
    try {
      const result = await apiClient.post<LogoutAllResponse>("/api/v1/auth/logout-all");
      return result.revoked_session_count;
    } finally {
      await logout();
    }
  }, [logout]);

  const refreshIdentity = useCallback(async () => {
    await bootstrap();
  }, [bootstrap]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      account,
      learner,
      accessToken: tokenState?.accessToken ?? null,
      login,
      register,
      logout,
      logoutAll,
      refreshIdentity,
    }),
    [status, account, learner, tokenState, login, register, logout, logoutAll, refreshIdentity]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { setAccessToken } from "@/lib/auth/token-store";
import { useAuth } from "@/hooks/useAuth";
import { server } from "@/tests/mocks/server";
import { renderWithProviders, screen, waitFor } from "@/tests/test-utils";

function LogoutButton() {
  const { logout, status } = useAuth();
  return (
    <div>
      <span>status: {status}</span>
      <button onClick={() => void logout()}>Log out</button>
    </div>
  );
}

describe("AuthProvider logout", () => {
  it("clears the TanStack Query cache and the in-memory access token on logout", async () => {
    server.use(http.post("/api/auth/logout", () => HttpResponse.json({ ok: true })));
    const user = userEvent.setup();

    const { queryClient } = renderWithProviders(<LogoutButton />);
    await waitFor(() => screen.getByText("status: unauthenticated"));

    queryClient.setQueryData(["some-cached-data"], { secret: "value" });
    setAccessToken({ accessToken: "abc", accessTokenExpiresAt: "2026-01-01T00:00:00Z" });
    expect(queryClient.getQueryData(["some-cached-data"])).toBeDefined();

    await user.click(screen.getByRole("button", { name: "Log out" }));

    await waitFor(() => expect(queryClient.getQueryData(["some-cached-data"])).toBeUndefined());
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  });

  it("clears the cache even if the backend logout call fails (always clears client-side)", async () => {
    server.use(http.post("/api/auth/logout", () => HttpResponse.json({ error: "down" }, { status: 500 })));
    const user = userEvent.setup();

    const { queryClient } = renderWithProviders(<LogoutButton />);
    await waitFor(() => screen.getByText("status: unauthenticated"));
    queryClient.setQueryData(["some-cached-data"], { secret: "value" });

    await user.click(screen.getByRole("button", { name: "Log out" }));

    await waitFor(() => expect(queryClient.getQueryData(["some-cached-data"])).toBeUndefined());
  });
});

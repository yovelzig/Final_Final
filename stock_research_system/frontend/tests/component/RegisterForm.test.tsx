import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { RegisterForm } from "@/components/auth/RegisterForm";
import { screen, waitFor } from "@/tests/test-utils";
import { renderWithAuthContext } from "@/tests/mocks/auth-context";

describe("RegisterForm", () => {
  it("blocks submission and shows an error when the passwords don't match", async () => {
    const user = userEvent.setup();
    const { authValue } = renderWithAuthContext(<RegisterForm />);

    await user.type(screen.getByLabelText("Display name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "Password123!");
    await user.type(screen.getByLabelText("Confirm password"), "Different123!");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
    expect(authValue.register).not.toHaveBeenCalled();
  });

  it("registers with matching passwords and the configured daily goal", async () => {
    const user = userEvent.setup();
    const { authValue } = renderWithAuthContext(<RegisterForm />);

    await user.type(screen.getByLabelText("Display name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "Password123!");
    await user.type(screen.getByLabelText("Confirm password"), "Password123!");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() =>
      expect(authValue.register).toHaveBeenCalledWith({
        email: "ada@example.com",
        password: "Password123!",
        displayName: "Ada Lovelace",
        dailyGoalMinutes: 10,
      })
    );
  });
});

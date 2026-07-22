import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LoginForm } from "@/components/auth/LoginForm";
import { FinQuestApiError } from "@/lib/api/client";
import { screen, waitFor } from "@/tests/test-utils";
import { renderWithAuthContext } from "@/tests/mocks/auth-context";

describe("LoginForm", () => {
  it("shows validation errors and never calls login for an invalid submission", async () => {
    const user = userEvent.setup();
    const { authValue } = renderWithAuthContext(<LoginForm />);

    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByText("Email is required.")).toBeInTheDocument();
    expect(authValue.login).not.toHaveBeenCalled();
  });

  it("submits trimmed, validated credentials to useAuth().login", async () => {
    const user = userEvent.setup();
    const { authValue } = renderWithAuthContext(<LoginForm />);

    await user.type(screen.getByLabelText("Email"), "learner@example.com");
    await user.type(screen.getByLabelText("Password"), "correct-password");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    await waitFor(() => expect(authValue.login).toHaveBeenCalledWith("learner@example.com", "correct-password"));
  });

  it("renders the backend's own safe error message and clears the password field on failure", async () => {
    const user = userEvent.setup();
    const login = async () => {
      throw new FinQuestApiError({ status: 401, code: "INVALID_CREDENTIALS", message: "Incorrect email or password." });
    };
    renderWithAuthContext(<LoginForm />, { login });

    await user.type(screen.getByLabelText("Email"), "learner@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByText("Incorrect email or password.")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });
});

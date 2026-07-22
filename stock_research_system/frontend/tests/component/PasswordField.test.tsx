import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { PasswordField } from "@/components/auth/PasswordField";
import { render, screen } from "@/tests/test-utils";

describe("PasswordField", () => {
  it("masks the password by default and reveals it on toggle", async () => {
    const user = userEvent.setup();
    render(<PasswordField label="Password" />);

    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");

    await user.click(screen.getByRole("button", { name: /show/i }));
    expect(input).toHaveAttribute("type", "text");

    await user.click(screen.getByRole("button", { name: /hide/i }));
    expect(input).toHaveAttribute("type", "password");
  });

  it("associates an error message via aria-describedby and role=alert", () => {
    render(<PasswordField label="Password" error="Too short." />);
    const input = screen.getByLabelText("Password");
    const error = screen.getByRole("alert");
    expect(error).toHaveTextContent("Too short.");
    expect(input.getAttribute("aria-describedby")).toContain(error.id);
    expect(input).toHaveAttribute("aria-invalid", "true");
  });
});

import { describe, expect, it } from "vitest";

import { loginFormSchema, passwordSchema, registerFormSchema } from "@/lib/validation/auth";

describe("loginFormSchema", () => {
  it("accepts a valid email and non-empty password", () => {
    const result = loginFormSchema.safeParse({ email: "learner@example.com", password: "anything" });
    expect(result.success).toBe(true);
  });

  it("rejects an invalid email", () => {
    const result = loginFormSchema.safeParse({ email: "not-an-email", password: "anything" });
    expect(result.success).toBe(false);
  });

  it("rejects an empty password", () => {
    const result = loginFormSchema.safeParse({ email: "learner@example.com", password: "" });
    expect(result.success).toBe(false);
  });
});

describe("passwordSchema", () => {
  it("accepts a password with three character classes and sufficient length", () => {
    expect(passwordSchema.safeParse("Password123").success).toBe(true);
  });

  it("rejects a password shorter than 10 characters", () => {
    expect(passwordSchema.safeParse("Short1!").success).toBe(false);
  });

  it("rejects a password with only two character classes (lowercase + digit)", () => {
    expect(passwordSchema.safeParse("alllowercase1").success).toBe(false);
  });

  it("rejects an all-lowercase-letters password (one character class)", () => {
    expect(passwordSchema.safeParse("alllowercaseletters").success).toBe(false);
  });
});

describe("registerFormSchema password confirmation", () => {
  const base = {
    displayName: "Ada",
    email: "ada@example.com",
    password: "Password123!",
    dailyGoalMinutes: 10,
  };

  it("accepts matching password and confirmPassword", () => {
    const result = registerFormSchema.safeParse({ ...base, confirmPassword: base.password });
    expect(result.success).toBe(true);
  });

  it("rejects a mismatched confirmPassword, attaching the error to that field", () => {
    const result = registerFormSchema.safeParse({ ...base, confirmPassword: "Different123!" });
    expect(result.success).toBe(false);
    if (!result.success) {
      const confirmError = result.error.issues.find((issue) => issue.path.join(".") === "confirmPassword");
      expect(confirmError).toBeDefined();
      expect(confirmError?.message).toBe("Passwords do not match.");
    }
  });

  it("rejects a daily goal outside the allowed range", () => {
    const result = registerFormSchema.safeParse({ ...base, confirmPassword: base.password, dailyGoalMinutes: 0 });
    expect(result.success).toBe(false);
  });
});

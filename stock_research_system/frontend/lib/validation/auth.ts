import { z } from "zod";

/**
 * Client-side mirror of the backend's password policy
 * (`application.identity.security.validate_password_policy`): 10-128
 * characters, at least 3 of {lowercase, uppercase, digit, symbol}.
 * This is UX only - the backend remains the sole source of truth and
 * re-validates independently (including the email-containment and
 * common-password checks this client-side mirror deliberately does
 * NOT duplicate, since those require the email value in-flight and a
 * word list only the server needs to own).
 */
const MIN_PASSWORD_LENGTH = 10;
const MAX_PASSWORD_LENGTH = 128;

function countCharacterClasses(password: string): number {
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^a-zA-Z0-9]/];
  return classes.filter((pattern) => pattern.test(password)).length;
}

export const passwordSchema = z
  .string()
  .min(MIN_PASSWORD_LENGTH, `Password must be at least ${MIN_PASSWORD_LENGTH} characters long.`)
  .max(MAX_PASSWORD_LENGTH, `Password must be at most ${MAX_PASSWORD_LENGTH} characters long.`)
  .refine(
    (value) => countCharacterClasses(value) >= 3,
    "Password must contain at least three of: a lowercase letter, an uppercase letter, a number, and a symbol."
  );

export const emailSchema = z.string().min(1, "Email is required.").email("Enter a valid email address.");

export const loginFormSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, "Password is required."),
});
export type LoginFormValues = z.infer<typeof loginFormSchema>;

export const registerFormSchema = z
  .object({
    displayName: z.string().min(1, "Display name is required.").max(150, "Display name is too long."),
    email: emailSchema,
    password: passwordSchema,
    confirmPassword: z.string().min(1, "Please confirm your password."),
    dailyGoalMinutes: z.coerce.number().int().min(5, "Daily goal must be at least 5 minutes.").max(240, "Daily goal must be at most 240 minutes."),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match.",
    path: ["confirmPassword"],
  });
export type RegisterFormValues = z.infer<typeof registerFormSchema>;

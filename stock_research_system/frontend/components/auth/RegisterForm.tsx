"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { FormField } from "@/components/ui/FormField";
import { PasswordField } from "@/components/auth/PasswordField";
import { FinQuestApiError } from "@/lib/api/client";
import { useAuth } from "@/hooks/useAuth";
import { registerFormSchema, type RegisterFormValues } from "@/lib/validation/auth";

export function RegisterForm() {
  const { register: registerAccount } = useAuth();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    resetField,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormValues>({
    resolver: zodResolver(registerFormSchema),
    defaultValues: { dailyGoalMinutes: 10 },
  });

  const onSubmit = async (values: RegisterFormValues) => {
    setSubmitError(null);
    try {
      await registerAccount({
        email: values.email,
        password: values.password,
        displayName: values.displayName,
        dailyGoalMinutes: values.dailyGoalMinutes,
      });
    } catch (error) {
      resetField("password");
      resetField("confirmPassword");
      if (error instanceof FinQuestApiError) {
        // The backend's own message is already safe to show verbatim
        // (e.g. "An account with this email address already exists.",
        // or a specific password-policy violation) - never invented here.
        setSubmitError(error.message);
      } else {
        setSubmitError("Something went wrong. Please try again.");
      }
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4 rounded-card border border-border bg-surface p-6 shadow-sm">
      <h1 className="text-xl font-bold text-slate-900">Create your account</h1>

      {submitError ? (
        <Alert tone="danger" role="alert">
          {submitError}
        </Alert>
      ) : null}

      <FormField label="Display name" autoComplete="name" error={errors.displayName?.message} {...register("displayName")} />
      <FormField label="Email" type="email" autoComplete="email" error={errors.email?.message} {...register("email")} />
      <PasswordField
        label="Password"
        autoComplete="new-password"
        hint="At least 10 characters, with at least 3 of: lowercase, uppercase, number, symbol."
        error={errors.password?.message}
        {...register("password")}
      />
      <PasswordField
        label="Confirm password"
        autoComplete="new-password"
        error={errors.confirmPassword?.message}
        {...register("confirmPassword")}
      />
      <FormField
        label="Daily goal (minutes)"
        type="number"
        min={5}
        max={240}
        error={errors.dailyGoalMinutes?.message}
        {...register("dailyGoalMinutes")}
      />

      <Button type="submit" isLoading={isSubmitting} className="mt-2 w-full">
        Create account
      </Button>

      <p className="text-center text-sm text-muted">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-primary hover:underline">
          Log in
        </Link>
      </p>
    </form>
  );
}

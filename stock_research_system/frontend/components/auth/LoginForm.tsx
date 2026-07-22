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
import { loginFormSchema, type LoginFormValues } from "@/lib/validation/auth";

export function LoginForm() {
  const { login } = useAuth();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    resetField,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginFormSchema) });

  const onSubmit = async (values: LoginFormValues) => {
    setSubmitError(null);
    try {
      await login(values.email, values.password);
    } catch (error) {
      // Never retain the password in the form after a failed attempt.
      resetField("password");
      if (error instanceof FinQuestApiError) {
        // The backend already returns the same generic message for
        // "unknown account" and "wrong password" - and a safe, non-
        // enumerating message for a locked account. Render it verbatim.
        setSubmitError(error.message);
      } else {
        setSubmitError("Something went wrong. Please try again.");
      }
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4 rounded-card border border-border bg-surface p-6 shadow-sm">
      <h1 className="text-xl font-bold text-slate-900">Log in</h1>

      {submitError ? (
        <Alert tone="danger" role="alert">
          {submitError}
        </Alert>
      ) : null}

      <FormField
        label="Email"
        type="email"
        autoComplete="email"
        error={errors.email?.message}
        {...register("email")}
      />
      <PasswordField
        label="Password"
        autoComplete="current-password"
        error={errors.password?.message}
        {...register("password")}
      />

      <Button type="submit" isLoading={isSubmitting} className="mt-2 w-full">
        Log in
      </Button>

      <p className="text-center text-sm text-muted">
        New to FinQuest?{" "}
        <Link href="/register" className="font-medium text-primary hover:underline">
          Create an account
        </Link>
      </p>
    </form>
  );
}

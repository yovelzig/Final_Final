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
import { useDictionary } from "@/providers/LocaleProvider";
import { registerFormSchema, type RegisterFormValues } from "@/lib/validation/auth";

export function RegisterForm() {
  const { register: registerAccount } = useAuth();
  const t = useDictionary();
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
        setSubmitError(t.auth.register.genericError);
      }
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4 rounded-card border border-border bg-surface p-6 shadow-sm">
      <h1 className="text-xl font-bold text-slate-900">{t.auth.register.title}</h1>

      {submitError ? (
        <Alert tone="danger" role="alert">
          {submitError}
        </Alert>
      ) : null}

      <FormField
        label={t.auth.register.displayName}
        autoComplete="name"
        error={errors.displayName?.message}
        {...register("displayName")}
      />
      <FormField
        label={t.auth.register.email}
        type="email"
        autoComplete="email"
        error={errors.email?.message}
        {...register("email")}
      />
      <PasswordField
        label={t.auth.register.password}
        autoComplete="new-password"
        hint={t.auth.register.passwordHint}
        showLabel={t.auth.passwordShow}
        hideLabel={t.auth.passwordHide}
        error={errors.password?.message}
        {...register("password")}
      />
      <PasswordField
        label={t.auth.register.confirmPassword}
        autoComplete="new-password"
        showLabel={t.auth.passwordShow}
        hideLabel={t.auth.passwordHide}
        error={errors.confirmPassword?.message}
        {...register("confirmPassword")}
      />
      <FormField
        label={t.auth.register.dailyGoal}
        type="number"
        min={5}
        max={240}
        error={errors.dailyGoalMinutes?.message}
        {...register("dailyGoalMinutes")}
      />

      <Button type="submit" isLoading={isSubmitting} className="mt-2 w-full">
        {t.auth.register.submit}
      </Button>

      <p className="text-center text-sm text-muted">
        {t.auth.register.haveAccount}{" "}
        <Link href="/login" className="font-medium text-primary hover:underline">
          {t.auth.register.logIn}
        </Link>
      </p>
    </form>
  );
}

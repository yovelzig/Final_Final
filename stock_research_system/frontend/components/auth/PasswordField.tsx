"use client";

import { useId, useState, type InputHTMLAttributes } from "react";

export interface PasswordFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label: string;
  error?: string;
  hint?: string;
}

export function PasswordField({ label, error, hint, id, className = "", ...props }: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const errorId = `${fieldId}-error`;
  const hintId = `${fieldId}-hint`;
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(" ") || undefined;

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={fieldId} className="text-sm font-medium text-slate-700">
        {label}
      </label>
      <div className="relative flex items-center">
        <input
          id={fieldId}
          type={visible ? "text" : "password"}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          autoComplete={props.autoComplete}
          className={`w-full rounded-lg border border-border bg-white px-3 py-2.5 pr-16 text-sm text-slate-900 placeholder:text-slate-400 focus:border-primary ${
            error ? "border-danger" : ""
          } ${className}`}
          {...props}
        />
        <button
          type="button"
          onClick={() => setVisible((current) => !current)}
          aria-pressed={visible}
          className="absolute right-2 rounded px-2 py-1 text-xs font-medium text-slate-500 hover:text-primary"
        >
          {visible ? "Hide" : "Show"}
          <span className="sr-only"> password</span>
        </button>
      </div>
      {hint && !error ? (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs font-medium text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

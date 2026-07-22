import { useId, type InputHTMLAttributes, type ReactNode } from "react";

export interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
  trailingAction?: ReactNode;
}

/** A labeled text input with a properly associated error message
 * (`aria-describedby` + `aria-invalid`) - the base building block for
 * every form in the app. */
export function FormField({ label, error, hint, trailingAction, id, className = "", ...props }: FormFieldProps) {
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
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={`w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-primary ${
            error ? "border-danger" : ""
          } ${className}`}
          {...props}
        />
        {trailingAction ? <div className="absolute right-2">{trailingAction}</div> : null}
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

import { useId, type ReactNode, type SelectHTMLAttributes } from "react";

export interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  error?: string;
  children: ReactNode;
}

export function SelectField({ label, error, id, className = "", children, ...props }: SelectFieldProps) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const errorId = `${fieldId}-error`;

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={fieldId} className="text-sm font-medium text-slate-700">
        {label}
      </label>
      <select
        id={fieldId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className={`w-full rounded-lg border border-border bg-white px-3 py-2.5 text-sm text-slate-900 focus:border-primary ${
          error ? "border-danger" : ""
        } ${className}`}
        {...props}
      >
        {children}
      </select>
      {error ? (
        <p id={errorId} role="alert" className="text-xs font-medium text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

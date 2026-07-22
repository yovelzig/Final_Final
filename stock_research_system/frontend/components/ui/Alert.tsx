import type { ReactNode } from "react";

export type AlertTone = "info" | "success" | "warning" | "danger";

const TONE_CLASSES: Record<AlertTone, string> = {
  info: "bg-primary-light text-primary border-primary/20",
  success: "bg-success-light text-success border-success/20",
  warning: "bg-warning-light text-warning border-warning/20",
  danger: "bg-danger-light text-danger border-danger/20",
};

export function Alert({
  tone = "info",
  title,
  children,
  role = "status",
}: {
  tone?: AlertTone;
  title?: string;
  children: ReactNode;
  role?: "status" | "alert";
}) {
  return (
    <div role={role} className={`rounded-lg border px-4 py-3 text-sm ${TONE_CLASSES[tone]}`}>
      {title ? <p className="font-semibold">{title}</p> : null}
      <div className={title ? "mt-1" : undefined}>{children}</div>
    </div>
  );
}

import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "primary" | "success" | "warning" | "danger";

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-slate-100 text-slate-700",
  primary: "bg-primary-light text-primary",
  success: "bg-success-light text-success",
  warning: "bg-warning-light text-warning",
  danger: "bg-danger-light text-danger",
};

/** Status is never conveyed by color alone - always pair with a text label. */
export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}>
      {children}
    </span>
  );
}

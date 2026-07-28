import type { ReactNode } from "react";

/**
 * A small labeled number/metric tile - used for XP, streak, and
 * portfolio-count style stats on the dashboard and in the app shell.
 * The only genuinely new primitive this phase needed: existing `Card`
 * is a generic container, not a metric display, and every screen that
 * needs one (dashboard, top bar) would otherwise hand-roll its own
 * markup.
 */
export function StatCard({
  label,
  value,
  icon,
  tone = "neutral",
  className = "",
}: {
  label: string;
  value: ReactNode;
  icon?: ReactNode;
  tone?: "neutral" | "primary" | "success";
  className?: string;
}) {
  const toneClasses =
    tone === "primary"
      ? "border-primary/20 bg-primary-light"
      : tone === "success"
        ? "border-success/20 bg-success-light"
        : "border-border bg-surface";

  return (
    <div className={`flex items-center gap-3 rounded-card border p-4 ${toneClasses} ${className}`}>
      {icon ? <span aria-hidden="true">{icon}</span> : null}
      <div className="flex min-w-0 flex-col">
        <span className="text-lg font-bold leading-tight text-slate-900">{value}</span>
        <span className="truncate text-xs font-medium text-muted">{label}</span>
      </div>
    </div>
  );
}

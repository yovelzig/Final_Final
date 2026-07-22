import Link from "next/link";

const ACTIONS = [
  { href: "/learn", label: "Continue learning", description: "Pick up your current path" },
  { href: "/practice", label: "Start daily practice", description: "Adaptive recommendations" },
  { href: "/diagnostic", label: "Start diagnostic", description: "Assess your current level" },
  { href: "/scenarios", label: "Explore scenarios", description: "Historical market decisions" },
  { href: "/portfolios", label: "Open portfolio", description: "Simulated investing" },
  { href: "/tutor", label: "Ask the tutor", description: "Grounded, cited answers" },
] as const;

export function QuickActions() {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {ACTIONS.map((action) => (
        <Link
          key={action.href}
          href={action.href}
          className="rounded-card border border-border bg-surface p-4 transition-colors hover:border-primary hover:bg-primary-light"
        >
          <p className="text-sm font-semibold text-slate-900">{action.label}</p>
          <p className="mt-1 text-xs text-muted">{action.description}</p>
        </Link>
      ))}
    </div>
  );
}

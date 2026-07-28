import type { ReactNode } from "react";

/** One alternating text+visual block on the landing page. Reused for
 * the five product-area sections so their layout, spacing, and
 * typography stay identical - only the copy and icon change. */
export function FeatureSection({
  eyebrow,
  title,
  description,
  icon,
  reverse = false,
}: {
  eyebrow: string;
  title: string;
  description: string;
  icon: ReactNode;
  reverse?: boolean;
}) {
  return (
    <div className={`flex flex-col items-center gap-8 lg:flex-row ${reverse ? "lg:flex-row-reverse" : ""}`}>
      <div className="flex-1">
        <div className="mb-3 inline-flex h-11 w-11 items-center justify-center rounded-lg bg-primary-light text-primary">
          {icon}
        </div>
        <p className="text-sm font-semibold uppercase tracking-wide text-primary">{eyebrow}</p>
        <h2 className="mt-1 text-2xl font-bold text-slate-900">{title}</h2>
        <p className="mt-3 max-w-lg text-base leading-relaxed text-muted">{description}</p>
      </div>
      <div className="flex-1">
        <div className="flex aspect-[4/3] w-full items-center justify-center rounded-card border border-border bg-gradient-to-br from-primary-light to-surface text-primary [&>svg]:h-20 [&>svg]:w-20 [&>svg]:opacity-70">
          {icon}
        </div>
      </div>
    </div>
  );
}

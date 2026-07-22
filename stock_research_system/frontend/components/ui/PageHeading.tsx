import type { ReactNode } from "react";

/** Every page renders exactly one of these - the page's single `<h1>`. */
export function PageHeading({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
        {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
      </div>
      {action ? <div>{action}</div> : null}
    </div>
  );
}

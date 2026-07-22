export function ProgressBar({
  value,
  max = 100,
  label,
}: {
  value: number;
  max?: number;
  label: string;
}) {
  const clamped = Math.min(max, Math.max(0, value));
  const percent = max > 0 ? (clamped / max) * 100 : 0;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-xs text-muted">
        <span>{label}</span>
        <span>
          {clamped}/{max}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={max}
        className="h-2 w-full overflow-hidden rounded-full bg-slate-100"
      >
        <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

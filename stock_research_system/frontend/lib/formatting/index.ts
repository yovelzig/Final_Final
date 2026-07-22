/** Locale-aware, pure formatting helpers - never do currency/percentage
 * math here, only presentation of already-computed backend values. */

export function formatCurrency(value: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
}

export function formatPercentage(value: number, options?: { signDisplay?: "always" | "auto" }): string {
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
    signDisplay: options?.signDisplay ?? "auto",
  }).format(value);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(value);
}

export function formatDate(isoString: string): string {
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(isoString));
}

export function formatDateTime(isoString: string): string {
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(isoString));
}

export function formatRelativeTime(isoString: string, now: Date = new Date()): string {
  const target = new Date(isoString);
  const diffMs = target.getTime() - now.getTime();
  const diffMinutes = Math.round(diffMs / 60_000);
  const formatter = new Intl.RelativeTimeFormat("en-US", { numeric: "auto" });

  const absMinutes = Math.abs(diffMinutes);
  if (absMinutes < 60) return formatter.format(diffMinutes, "minute");
  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) return formatter.format(diffHours, "hour");
  const diffDays = Math.round(diffHours / 24);
  return formatter.format(diffDays, "day");
}

/** Parses a learner-entered numeric-input exercise answer in a
 * locale-safe way: strips thousands separators, accepts a leading
 * minus sign and a single decimal point, and returns `null` (never
 * `NaN`) for anything that isn't a clean number - the caller decides
 * how to surface that as a validation error. Never rounds or clamps:
 * grading correctness is entirely the backend's responsibility. */
export function parseNumericInput(raw: string): number | null {
  const trimmed = raw.trim().replace(/,/g, "");
  if (trimmed === "" || !/^-?\d*\.?\d+$/.test(trimmed)) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

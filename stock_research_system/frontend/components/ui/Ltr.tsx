import type { ReactNode } from "react";

/**
 * Wraps ticker symbols, currency amounts, percentages, and other
 * numeral-heavy content that must stay left-to-right and un-mirrored
 * even inside an RTL (Hebrew) page - e.g. "$1,234.56" or "AAPL"
 * embedded mid-sentence. `unicode-bidi: isolate` (via the
 * `bidi-isolate` global class) stops the surrounding Hebrew sentence
 * from reordering the punctuation inside this span.
 */
export function Ltr({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span dir="ltr" className={`bidi-isolate inline-block ${className}`}>
      {children}
    </span>
  );
}

/** Small, non-directional illustrative icons for the landing page.
 * None of these imply reading direction (no arrows/chevrons), so they
 * never need to be mirrored for RTL. */

const BASE_PROPS = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export function LearningPathIcon({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg {...BASE_PROPS} className={className}>
      <path d="M4 19V5a1 1 0 0 1 1-1h9l6 6v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1Z" />
      <path d="M13 4v6h6M8 13h8M8 17h5" />
    </svg>
  );
}

export function AdaptiveIcon({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg {...BASE_PROPS} className={className}>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="12" cy="12" r="0.6" fill="currentColor" />
    </svg>
  );
}

export function TutorIcon({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg {...BASE_PROPS} className={className}>
      <path d="M4 5h16v10H9l-4 4v-4H4Z" />
      <path d="M8 9h8M8 12h5" />
    </svg>
  );
}

export function ScenarioIcon({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg {...BASE_PROPS} className={className}>
      <path d="M4 19h16M4 19V6m4 13-2-6 5-2 3 4 5-7" />
    </svg>
  );
}

export function PortfolioIcon({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg {...BASE_PROPS} className={className}>
      <path d="M3 8h18v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8Z" />
      <path d="M8 8V6a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

export function CheckIcon({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg {...BASE_PROPS} className={className}>
      <path d="m5 13 4 4L19 7" />
    </svg>
  );
}

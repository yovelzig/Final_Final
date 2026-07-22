import type { NavItem } from "@/components/layout/nav-items";

const PATHS: Record<NavItem["icon"], string> = {
  dashboard: "M4 4h7v7H4V4zm9 0h7v7h-7V4zM4 13h7v7H4v-7zm9 0h7v7h-7v-7z",
  learn: "M4 6.5A2.5 2.5 0 0 1 6.5 4H20v13.5A2.5 2.5 0 0 1 17.5 20H4V6.5z",
  practice: "M12 2 3 7l9 5 9-5-9-5zm-9 8 9 5 9-5M3 15l9 5 9-5",
  scenarios: "M4 19V5m0 14h16M4 19l5-6 4 3 6-8",
  portfolio: "M3 7h18M3 7v12a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1V7M3 7l2-3h14l2 3",
  tutor: "M8 10h.01M12 10h.01M16 10h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
  coach: "M13 2 3 14h7l-1 8 11-13h-7l1-7z",
  settings:
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm7.4-3a7.4 7.4 0 0 0-.15-1.5l2-1.55-2-3.46-2.36.95a7.5 7.5 0 0 0-2.6-1.5L14 2h-4l-.3 2.94a7.5 7.5 0 0 0-2.6 1.5l-2.36-.95-2 3.46 2 1.55A7.4 7.4 0 0 0 4.6 12c0 .51.05 1 .15 1.5l-2 1.55 2 3.46 2.36-.95c.75.64 1.63 1.15 2.6 1.5L10 22h4l.3-2.94a7.5 7.5 0 0 0 2.6-1.5l2.36.95 2-3.46-2-1.55c.1-.5.15-.99.15-1.5z",
  admin: "M9 12l2 2 4-4m5-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
};

export function NavIcon({ icon, className = "h-5 w-5" }: { icon: NavItem["icon"]; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <path d={PATHS[icon]} />
    </svg>
  );
}

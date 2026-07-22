export interface NavItem {
  href: string;
  label: string;
  icon: "dashboard" | "learn" | "practice" | "scenarios" | "portfolio" | "tutor" | "coach" | "settings" | "admin";
}

export const PRIMARY_NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: "dashboard" },
  { href: "/learn", label: "Learn", icon: "learn" },
  { href: "/practice", label: "Practice", icon: "practice" },
  { href: "/scenarios", label: "Scenarios", icon: "scenarios" },
  { href: "/portfolios", label: "Portfolio", icon: "portfolio" },
  { href: "/tutor", label: "Tutor", icon: "tutor" },
  { href: "/coach", label: "Coach", icon: "coach" },
];

export const SECONDARY_NAV_ITEMS: NavItem[] = [{ href: "/settings", label: "Settings", icon: "settings" }];

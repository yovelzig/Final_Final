import type { Dictionary } from "@/lib/i18n/types";

type NavIcon = "dashboard" | "learn" | "practice" | "scenarios" | "portfolio" | "tutor" | "coach" | "settings" | "admin";

/** `labelKey` looks up its display text from `Dictionary["nav"]` at
 * render time (see `Sidebar`/`BottomNav`) instead of storing English
 * text directly, so the same item list works for every locale. */
export interface NavItem {
  href: string;
  labelKey: keyof Pick<
    Dictionary["nav"],
    "dashboard" | "learn" | "practice" | "scenarios" | "portfolio" | "tutor" | "coach" | "settings" | "admin"
  >;
  icon: NavIcon;
}

export const PRIMARY_NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", labelKey: "dashboard", icon: "dashboard" },
  { href: "/learn", labelKey: "learn", icon: "learn" },
  { href: "/practice", labelKey: "practice", icon: "practice" },
  { href: "/scenarios", labelKey: "scenarios", icon: "scenarios" },
  { href: "/portfolios", labelKey: "portfolio", icon: "portfolio" },
  { href: "/tutor", labelKey: "tutor", icon: "tutor" },
  { href: "/coach", labelKey: "coach", icon: "coach" },
];

export const SECONDARY_NAV_ITEMS: NavItem[] = [{ href: "/settings", labelKey: "settings", icon: "settings" }];

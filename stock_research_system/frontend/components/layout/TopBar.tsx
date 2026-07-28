"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { PRIMARY_NAV_ITEMS, SECONDARY_NAV_ITEMS } from "@/components/layout/nav-items";
import { ProfileMenu } from "@/components/layout/ProfileMenu";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { Ltr } from "@/components/ui/Ltr";
import { useDashboard } from "@/hooks/useDashboard";
import { useDictionary } from "@/providers/LocaleProvider";

const ALL_NAV_ITEMS = [...PRIMARY_NAV_ITEMS, ...SECONDARY_NAV_ITEMS];

/** The one top header for every breakpoint: brand (mobile/tablet
 * only - desktop already shows it in `Sidebar`), current page title,
 * real XP/streak, language selector, and the profile menu. RTL and
 * LTR share this exact markup; only the CSS direction context
 * changes. */
export function TopBar() {
  const pathname = usePathname();
  const t = useDictionary();
  const dashboardQuery = useDashboard();

  const activeItem = ALL_NAV_ITEMS.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`));
  const pageTitle = activeItem ? t.nav[activeItem.labelKey] : t.common.finquest;

  const dashboard = dashboardQuery.isSuccess ? dashboardQuery.data : null;
  const streakDays = dashboard?.current_streak_days ?? 0;

  return (
    <header className="flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-3 lg:px-8">
      <div className="flex min-w-0 items-center gap-3">
        <Link href="/dashboard" className="shrink-0 text-lg font-bold text-primary lg:hidden">
          {t.common.finquest}
        </Link>
        <h1 className="truncate text-base font-semibold text-slate-900 lg:text-lg" aria-live="polite">
          {pageTitle}
        </h1>
      </div>

      <div className="flex shrink-0 items-center gap-2 sm:gap-3">
        {dashboard ? (
          <span className="hidden items-center gap-1 rounded-full bg-primary-light px-3 py-1 text-xs font-semibold text-primary sm:inline-flex">
            <Ltr>{dashboard.total_xp}</Ltr> {t.appShell.xpLabel}
          </span>
        ) : null}
        {streakDays > 0 ? (
          <span className="hidden items-center gap-1 rounded-full bg-success-light px-3 py-1 text-xs font-semibold text-success sm:inline-flex">
            <Ltr>{streakDays}</Ltr> {t.appShell.streakLabel}
          </span>
        ) : null}
        <LanguageSwitcher />
        <ProfileMenu />
      </div>
    </header>
  );
}

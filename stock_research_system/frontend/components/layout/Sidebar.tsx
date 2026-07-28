"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NavIcon } from "@/components/layout/NavIcon";
import { PRIMARY_NAV_ITEMS, SECONDARY_NAV_ITEMS } from "@/components/layout/nav-items";
import { useAuth } from "@/hooks/useAuth";
import { useDictionary } from "@/providers/LocaleProvider";

export function Sidebar() {
  const pathname = usePathname();
  const { account } = useAuth();
  const t = useDictionary();

  return (
    <nav
      aria-label={t.nav.primaryNavLabel}
      className="hidden w-60 shrink-0 flex-col border-e border-border bg-surface px-3 py-6 lg:flex"
    >
      <div className="mb-8 px-3">
        <span className="text-xl font-bold text-primary">{t.common.finquest}</span>
      </div>

      <ul className="flex flex-1 flex-col gap-1">
        {PRIMARY_NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                  isActive ? "bg-primary-light text-primary" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                <NavIcon icon={item.icon} />
                {t.nav[item.labelKey]}
              </Link>
            </li>
          );
        })}
      </ul>

      <div className="mt-6 border-t border-border pt-4">
        <ul className="flex flex-col gap-1">
          {SECONDARY_NAV_ITEMS.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-100"
              >
                <NavIcon icon={item.icon} />
                {t.nav[item.labelKey]}
              </Link>
            </li>
          ))}
          {account?.role === "ADMIN" ? (
            <li>
              <Link
                href="/admin/evaluations"
                className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-100"
              >
                <NavIcon icon="admin" />
                {t.nav.admin}
              </Link>
            </li>
          ) : null}
        </ul>
      </div>
    </nav>
  );
}

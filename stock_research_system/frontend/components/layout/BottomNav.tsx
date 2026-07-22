"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NavIcon } from "@/components/layout/NavIcon";
import { PRIMARY_NAV_ITEMS } from "@/components/layout/nav-items";

export function BottomNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-10 flex border-t border-border bg-surface px-1 py-1 lg:hidden"
      style={{ paddingBottom: "max(0.25rem, env(safe-area-inset-bottom))" }}
    >
      {PRIMARY_NAV_ITEMS.map((item) => {
        const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={isActive ? "page" : undefined}
            className={`flex flex-1 flex-col items-center gap-0.5 rounded-lg py-2 text-[11px] font-medium ${
              isActive ? "text-primary" : "text-slate-500"
            }`}
          >
            <NavIcon icon={item.icon} className="h-5 w-5" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

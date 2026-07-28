"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/hooks/useAuth";
import { useDictionary } from "@/providers/LocaleProvider";

/** Account identity + settings + log out, in one place - the single
 * owner of "log out" in the app shell (the sidebar no longer
 * duplicates it). A minimal accessible disclosure menu: no portal, no
 * focus trap library - just Escape-to-close, click-outside-to-close,
 * and standard `menu`/`menuitem` roles, which is all a two-item menu
 * needs. */
export function ProfileMenu() {
  const { account, logout } = useAuth();
  const t = useDictionary();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  if (!account) return null;

  const initial = account.display_name.trim().charAt(0).toUpperCase() || "?";

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t.appShell.profileMenuLabel}
        className="flex items-center gap-2 rounded-full border border-border bg-surface py-1 pe-3 ps-1 text-sm font-medium text-slate-700 hover:bg-slate-50"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary-light text-xs font-bold text-primary">
          {initial}
        </span>
        <span className="hidden max-w-[10rem] truncate sm:inline">{account.display_name}</span>
      </button>

      {open ? (
        <div
          role="menu"
          aria-label={t.appShell.profileMenuLabel}
          className="absolute end-0 z-20 mt-2 w-48 rounded-lg border border-border bg-surface py-1 shadow-md"
        >
          <p className="truncate px-3 py-2 text-xs text-muted">{account.display_name}</p>
          <Link
            href="/settings"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="block px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
          >
            {t.appShell.settings}
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              void logout();
            }}
            className="block w-full px-3 py-2 text-start text-sm text-slate-700 hover:bg-slate-100"
          >
            {t.appShell.logOut}
          </button>
        </div>
      ) : null}
    </div>
  );
}

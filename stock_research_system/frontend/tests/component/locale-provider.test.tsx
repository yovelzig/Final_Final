import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { LOCALE_COOKIE_NAME } from "@/lib/i18n/config";
import { useDictionary, useLocale } from "@/providers/LocaleProvider";
import { renderWithProviders, screen } from "@/tests/test-utils";

function readLocaleCookie(): string | undefined {
  return document.cookie
    .split("; ")
    .find((entry) => entry.startsWith(`${LOCALE_COOKIE_NAME}=`))
    ?.split("=")[1];
}

function clearLocaleCookie() {
  document.cookie = `${LOCALE_COOKIE_NAME}=; path=/; max-age=0`;
}

function Probe() {
  const { locale, dir } = useLocale();
  const t = useDictionary();
  return (
    <div>
      <p data-testid="locale">{locale}</p>
      <p data-testid="dir">{dir}</p>
      <p data-testid="title">{t.dashboard.subtitle}</p>
      <LanguageSwitcher />
    </div>
  );
}

describe("LocaleProvider + LanguageSwitcher", () => {
  afterEach(() => clearLocaleCookie());

  it("sets html lang/dir from the initial locale on mount (server-read cookie value)", () => {
    renderWithProviders(<Probe />, { locale: "he" });

    expect(document.documentElement.lang).toBe("he");
    expect(document.documentElement.dir).toBe("rtl");
    expect(screen.getByTestId("locale")).toHaveTextContent("he");
    expect(screen.getByTestId("dir")).toHaveTextContent("rtl");
  });

  it("defaults to ltr English when the initial locale is en", () => {
    renderWithProviders(<Probe />, { locale: "en" });

    expect(document.documentElement.lang).toBe("en");
    expect(document.documentElement.dir).toBe("ltr");
  });

  it("switching language updates html lang/dir, the dictionary, and persists a cookie", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Probe />, { locale: "en" });

    expect(screen.getByTestId("title")).toHaveTextContent("Your learning at a glance.");

    await user.click(screen.getByRole("button", { name: "עברית" }));

    expect(document.documentElement.lang).toBe("he");
    expect(document.documentElement.dir).toBe("rtl");
    expect(screen.getByTestId("locale")).toHaveTextContent("he");
    expect(screen.getByTestId("title")).toHaveTextContent("הלמידה שלכם במבט אחד.");
    expect(readLocaleCookie()).toBe("he");
  });

  it("a fresh mount honors whatever locale is passed in (simulating a reload that re-reads the persisted cookie)", () => {
    // `app/layout.tsx` reads the cookie server-side and passes it as
    // the provider's initial locale - simulate that hand-off directly
    // rather than reaching into `document.cookie` parsing logic that
    // belongs to Next.js, not this app.
    renderWithProviders(<Probe />, { locale: "he" });
    expect(screen.getByTestId("locale")).toHaveTextContent("he");
    expect(document.documentElement.dir).toBe("rtl");
  });
});

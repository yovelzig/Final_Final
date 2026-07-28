"use client";

import Link from "next/link";

import { FeatureSection } from "@/components/marketing/FeatureSection";
import {
  AdaptiveIcon,
  CheckIcon,
  LearningPathIcon,
  PortfolioIcon,
  ScenarioIcon,
  TutorIcon,
} from "@/components/marketing/icons";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { Ltr } from "@/components/ui/Ltr";
import { useDictionary } from "@/providers/LocaleProvider";

export default function HomePage() {
  const t = useDictionary();

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <a
        href="#main-content"
        className="sr-only-focusable fixed start-2 top-2 z-50 rounded-md bg-primary px-3 py-2 text-sm text-white"
      >
        {t.nav.skipToContent}
      </a>

      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
          <span className="text-xl font-bold text-primary">{t.common.finquest}</span>
          <nav aria-label={t.nav.primaryNavLabel} className="flex items-center gap-3">
            <LanguageSwitcher />
            <Link href="/login" className="text-sm font-medium text-slate-700 hover:text-primary">
              {t.landing.nav.login}
            </Link>
            <Link
              href="/register"
              className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-primary-hover"
            >
              {t.landing.nav.getStarted}
            </Link>
          </nav>
        </div>
      </header>

      <main id="main-content" className="flex-1">
        {/* Hero */}
        <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:px-8 lg:py-24">
          <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
            <div>
              <p className="text-sm font-semibold uppercase tracking-wide text-primary">{t.landing.hero.eyebrow}</p>
              <h1 className="mt-3 text-4xl font-bold leading-tight text-slate-900 sm:text-5xl">{t.landing.hero.title}</h1>
              <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted">{t.landing.hero.subtitle}</p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Link
                  href="/register"
                  className="rounded-lg bg-primary px-6 py-3 text-center text-sm font-semibold text-white transition-colors hover:bg-primary-hover"
                >
                  {t.landing.hero.primaryCta}
                </Link>
                <Link
                  href="/login"
                  className="rounded-lg border border-border bg-surface px-6 py-3 text-center text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50"
                >
                  {t.landing.hero.secondaryCta}
                </Link>
              </div>
            </div>

            {/* Product preview mockup - illustrative chrome only, no real learner data */}
            <div className="rounded-card border border-border bg-surface p-5 shadow-md" aria-hidden="true">
              <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted">{t.landing.preview.caption}</p>
              <div className="rounded-lg border border-border bg-background p-4">
                <p className="text-xs font-medium text-muted">{t.landing.preview.lessonLabel}</p>
                <p className="mt-1 text-base font-semibold text-slate-900">{t.landing.preview.lessonTitle}</p>
                <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full w-2/3 rounded-full bg-primary" />
                </div>
                <div className="mt-4 flex gap-2">
                  <span className="rounded-full bg-primary-light px-3 py-1 text-xs font-semibold text-primary">
                    <Ltr>420</Ltr> {t.landing.preview.xpLabel}
                  </span>
                  <span className="rounded-full bg-success-light px-3 py-1 text-xs font-semibold text-success">
                    <Ltr>5</Ltr> {t.landing.preview.streakLabel}
                  </span>
                </div>
              </div>
              <div className="mt-3 rounded-lg border border-border bg-background p-4">
                <p className="text-xs font-medium text-muted">{t.landing.preview.tutorPreviewQuestion}</p>
                <p className="mt-2 text-sm text-slate-700">{t.landing.preview.tutorPreviewAnswer}</p>
                <p className="mt-2 text-xs text-primary">[1] {t.landing.sections.learningPath.title}</p>
              </div>
            </div>
          </div>
        </section>

        {/* Feature sections */}
        <section className="mx-auto flex max-w-6xl flex-col gap-20 px-4 py-12 sm:px-6 lg:px-8">
          <FeatureSection
            eyebrow={t.landing.sections.learningPath.eyebrow}
            title={t.landing.sections.learningPath.title}
            description={t.landing.sections.learningPath.description}
            icon={<LearningPathIcon />}
          />
          <FeatureSection
            eyebrow={t.landing.sections.adaptive.eyebrow}
            title={t.landing.sections.adaptive.title}
            description={t.landing.sections.adaptive.description}
            icon={<AdaptiveIcon />}
            reverse
          />
          <FeatureSection
            eyebrow={t.landing.sections.tutor.eyebrow}
            title={t.landing.sections.tutor.title}
            description={t.landing.sections.tutor.description}
            icon={<TutorIcon />}
          />
          <FeatureSection
            eyebrow={t.landing.sections.scenarios.eyebrow}
            title={t.landing.sections.scenarios.title}
            description={t.landing.sections.scenarios.description}
            icon={<ScenarioIcon />}
            reverse
          />
          <FeatureSection
            eyebrow={t.landing.sections.portfolio.eyebrow}
            title={t.landing.sections.portfolio.title}
            description={t.landing.sections.portfolio.description}
            icon={<PortfolioIcon />}
          />
        </section>

        {/* Trust & safety */}
        <section className="bg-surface py-16">
          <div className="mx-auto max-w-4xl px-4 text-center sm:px-6 lg:px-8">
            <h2 className="text-3xl font-bold text-slate-900">{t.landing.trust.title}</h2>
            <p className="mx-auto mt-3 max-w-2xl text-base text-muted">{t.landing.trust.description}</p>
            <ul className="mt-8 grid grid-cols-1 gap-4 text-start sm:grid-cols-2">
              {t.landing.trust.points.map((point) => (
                <li key={point} className="flex items-start gap-3 rounded-card border border-border bg-background p-4">
                  <span className="mt-0.5 shrink-0 text-success">
                    <CheckIcon />
                  </span>
                  <span className="text-sm text-slate-700">{point}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Final CTA */}
        <section className="mx-auto max-w-4xl px-4 py-20 text-center sm:px-6 lg:px-8">
          <h2 className="text-3xl font-bold text-slate-900">{t.landing.finalCta.title}</h2>
          <p className="mx-auto mt-3 max-w-xl text-base text-muted">{t.landing.finalCta.description}</p>
          <Link
            href="/register"
            className="mt-8 inline-block rounded-lg bg-primary px-8 py-3.5 text-sm font-semibold text-white transition-colors hover:bg-primary-hover"
          >
            {t.landing.finalCta.cta}
          </Link>
        </section>
      </main>

      <footer className="border-t border-border bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 gap-8 sm:grid-cols-3">
            <div>
              <span className="text-lg font-bold text-primary">{t.common.finquest}</span>
              <p className="mt-2 max-w-xs text-sm text-muted">{t.landing.footer.tagline}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t.landing.footer.product}</p>
              <ul className="mt-3 flex flex-col gap-2 text-sm text-slate-600">
                <li>{t.landing.footer.learn}</li>
                <li>{t.landing.footer.tutor}</li>
                <li>{t.landing.footer.scenarios}</li>
                <li>{t.landing.footer.portfolio}</li>
              </ul>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t.landing.footer.account}</p>
              <ul className="mt-3 flex flex-col gap-2 text-sm">
                <li>
                  <Link href="/login" className="text-slate-600 hover:text-primary">
                    {t.landing.footer.login}
                  </Link>
                </li>
                <li>
                  <Link href="/register" className="text-slate-600 hover:text-primary">
                    {t.landing.footer.register}
                  </Link>
                </li>
              </ul>
            </div>
          </div>
          <p className="mt-10 border-t border-border pt-6 text-xs text-muted">
            © <Ltr>{new Date().getFullYear()}</Ltr> {t.landing.footer.copyright}
          </p>
        </div>
      </footer>
    </div>
  );
}

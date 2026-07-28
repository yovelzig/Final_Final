"use client";

import Link from "next/link";

import { Button } from "@/components/ui/Button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Ltr } from "@/components/ui/Ltr";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { MasteryList } from "@/components/dashboard/MasteryList";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { formatCurrency } from "@/lib/formatting";
import { interpolate } from "@/lib/i18n";
import { useAuth } from "@/hooks/useAuth";
import { useDashboard, useMastery } from "@/hooks/useDashboard";
import { usePortfolios } from "@/hooks/usePortfolios";
import { useDictionary, useLocale } from "@/providers/LocaleProvider";

export default function DashboardPage() {
  const { account } = useAuth();
  const { locale } = useLocale();
  const t = useDictionary();
  const dashboardQuery = useDashboard();
  const masteryQuery = useMastery();
  const portfoliosQuery = usePortfolios();

  return (
    <div>
      <PageHeading
        title={account ? interpolate(t.dashboard.welcomeBack, { name: account.display_name }) : t.dashboard.welcomeGeneric}
        description={t.dashboard.subtitle}
      />

      {dashboardQuery.isPending ? (
        <LoadingSkeletonCard />
      ) : dashboardQuery.isError ? (
        <ErrorState error={dashboardQuery.error} onRetry={() => void dashboardQuery.refetch()} />
      ) : (
        <div className="flex flex-col gap-6">
          {/* Continue learning */}
          <Card>
            <CardHeader>
              <CardTitle>{t.dashboard.continueLearning.title}</CardTitle>
            </CardHeader>
            {dashboardQuery.data.current_lesson_id ? (
              <Link href={`/lessons/${dashboardQuery.data.current_lesson_id}`}>
                <Button>{t.dashboard.continueLearning.cta}</Button>
              </Link>
            ) : dashboardQuery.data.active_path_id ? (
              <Link href={`/learn/${dashboardQuery.data.active_path_id}`}>
                <Button>{t.dashboard.continueLearning.cta}</Button>
              </Link>
            ) : (
              <EmptyState
                title={t.dashboard.continueLearning.emptyTitle}
                description={t.dashboard.continueLearning.emptyDescription}
                action={
                  <Link href="/learn">
                    <Button size="sm">{t.dashboard.continueLearning.emptyCta}</Button>
                  </Link>
                }
              />
            )}
          </Card>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Progress */}
            <Card>
              <CardHeader>
                <CardTitle>{t.dashboard.progress.title}</CardTitle>
                <CardDescription>{t.dashboard.progress.description}</CardDescription>
              </CardHeader>
              {dashboardQuery.data.total_lessons > 0 ? (
                <ProgressBar
                  label={t.dashboard.progress.lessonsCompleted}
                  value={dashboardQuery.data.completed_lessons}
                  max={dashboardQuery.data.total_lessons}
                />
              ) : (
                <p className="text-sm text-muted">{t.emptyState.genericDescription}</p>
              )}
              {dashboardQuery.data.active_misconceptions.length > 0 ? (
                <div className="mt-4 rounded-lg bg-warning-light px-3 py-2 text-xs text-warning">
                  {dashboardQuery.data.active_misconceptions.length === 1
                    ? t.dashboard.progress.misconceptionsOne
                    : interpolate(t.dashboard.progress.misconceptionsOther, {
                        count: dashboardQuery.data.active_misconceptions.length,
                      })}
                </div>
              ) : null}
            </Card>

            {/* Mastery */}
            <Card>
              <CardHeader>
                <CardTitle>{t.dashboard.mastery.title}</CardTitle>
                <CardDescription>{t.dashboard.mastery.description}</CardDescription>
              </CardHeader>
              {masteryQuery.isPending ? (
                <LoadingSkeletonCard />
              ) : masteryQuery.isError ? (
                <ErrorState error={masteryQuery.error} onRetry={() => void masteryQuery.refetch()} />
              ) : (
                <MasteryList items={masteryQuery.data.items} />
              )}
            </Card>

            {/* Virtual portfolio snapshot */}
            <Card>
              <CardHeader>
                <CardTitle>{t.dashboard.portfolio.title}</CardTitle>
                <CardDescription>{t.dashboard.portfolio.description}</CardDescription>
              </CardHeader>
              {portfoliosQuery.isPending ? (
                <LoadingSkeletonCard />
              ) : portfoliosQuery.isError ? (
                <ErrorState error={portfoliosQuery.error} onRetry={() => void portfoliosQuery.refetch()} />
              ) : portfoliosQuery.data[0] ? (
                <div className="flex flex-col gap-3">
                  <p className="text-sm text-slate-700">
                    <Ltr>{portfoliosQuery.data.length}</Ltr> {t.dashboard.portfolio.holdingsLabel}
                  </p>
                  <p className="text-2xl font-bold text-slate-900">
                    <Ltr>{formatCurrency(portfoliosQuery.data[0].cash_balance, portfoliosQuery.data[0].base_currency, locale)}</Ltr>
                  </p>
                  <Link href={`/portfolios/${portfoliosQuery.data[0].portfolio_id}`} className="self-start">
                    <Button size="sm" variant="secondary">
                      {t.dashboard.portfolio.cta}
                    </Button>
                  </Link>
                </div>
              ) : (
                <EmptyState
                  title={t.dashboard.portfolio.emptyTitle}
                  description={t.dashboard.portfolio.emptyDescription}
                  action={
                    <Link href="/portfolios/new">
                      <Button size="sm">{t.dashboard.portfolio.emptyCta}</Button>
                    </Link>
                  }
                />
              )}
            </Card>

            {/* Scenario shortcut */}
            <Card>
              <CardHeader>
                <CardTitle>{t.dashboard.scenarioShortcut.title}</CardTitle>
                <CardDescription>{t.dashboard.scenarioShortcut.description}</CardDescription>
              </CardHeader>
              <Link href="/scenarios">
                <Button size="sm" variant="secondary">
                  {t.dashboard.scenarioShortcut.cta}
                </Button>
              </Link>
            </Card>

            {/* Coach shortcut */}
            <Card>
              <CardHeader>
                <CardTitle>{t.dashboard.coachShortcut.title}</CardTitle>
                <CardDescription>{t.dashboard.coachShortcut.description}</CardDescription>
              </CardHeader>
              <Link href="/coach">
                <Button size="sm" variant="secondary">
                  {t.dashboard.coachShortcut.cta}
                </Button>
              </Link>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

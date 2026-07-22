"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { formatCurrency } from "@/lib/formatting";
import { usePortfolios } from "@/hooks/usePortfolios";

export default function PortfoliosPage() {
  const portfoliosQuery = usePortfolios();

  return (
    <div>
      <PageHeading
        title="Virtual portfolios"
        description="Practice investing with simulated money against real historical prices."
        action={
          <Link href="/portfolios/new">
            <Button>New portfolio</Button>
          </Link>
        }
      />

      {portfoliosQuery.isPending ? (
        <LoadingSkeletonCard />
      ) : portfoliosQuery.isError ? (
        <ErrorState error={portfoliosQuery.error} onRetry={() => void portfoliosQuery.refetch()} />
      ) : portfoliosQuery.data.length === 0 ? (
        <EmptyState
          title="No portfolios yet"
          description="Create a virtual portfolio to start practicing trade decisions."
          action={
            <Link href="/portfolios/new">
              <Button>Create your first portfolio</Button>
            </Link>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {portfoliosQuery.data.map((portfolio) => (
            <Link
              key={portfolio.portfolio_id}
              href={`/portfolios/${portfolio.portfolio_id}`}
              className="rounded-card border border-border bg-surface p-5 transition-shadow hover:shadow-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring"
            >
              <div className="mb-2 flex items-center gap-2">
                <Badge tone={portfolio.status === "ACTIVE" ? "success" : "neutral"}>{portfolio.status}</Badge>
              </div>
              <h2 className="text-base font-semibold text-slate-900">{portfolio.name}</h2>
              <p className="mt-1 text-sm text-muted">Cash balance: {formatCurrency(portfolio.cash_balance)}</p>
              <p className="mt-1 text-xs text-muted">Started with {formatCurrency(portfolio.initial_cash)}</p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

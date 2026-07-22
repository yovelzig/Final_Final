"use client";

import { use } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { TickerLabel } from "@/components/portfolios/TickerLabel";
import { AskTutorButton } from "@/components/tutor/AskTutorButton";
import { formatCurrency, formatDateTime, formatPercentage } from "@/lib/formatting";
import { usePortfolioOverview } from "@/hooks/usePortfolios";

export default function PortfolioDetailPage({ params }: { params: Promise<{ portfolioId: string }> }) {
  const { portfolioId } = use(params);
  const overviewQuery = usePortfolioOverview(portfolioId);

  if (overviewQuery.isPending) {
    return <LoadingSkeletonCard />;
  }
  if (overviewQuery.isError) {
    return <ErrorState error={overviewQuery.error} onRetry={() => void overviewQuery.refetch()} />;
  }

  const { portfolio, position_valuations, latest_risk_assessment, recent_transactions, recent_journal_entries } =
    overviewQuery.data;

  return (
    <div>
      <PageHeading
        title={portfolio.name}
        description={`Cash balance: ${formatCurrency(portfolio.cash_balance)} · Started with ${formatCurrency(portfolio.initial_cash)}`}
        action={
          <div className="flex gap-2">
            <AskTutorButton request={{ context_type: "PORTFOLIO_EXPLANATION", portfolio_id: portfolioId }} />
            <Link href={`/portfolios/${portfolioId}/journal`}>
              <Button variant="ghost">Journal</Button>
            </Link>
            <Link href={`/portfolios/${portfolioId}/trade`}>
              <Button>Trade</Button>
            </Link>
          </div>
        }
      />

      <div className="flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Positions</CardTitle>
          </CardHeader>
          {position_valuations.length === 0 ? (
            <p className="text-sm text-muted">No open positions yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-border text-xs text-muted">
                    <th className="py-2 pr-4">Security</th>
                    <th className="py-2 pr-4">Quantity</th>
                    <th className="py-2 pr-4">Market value</th>
                    <th className="py-2 pr-4">Unrealized P/L</th>
                    <th className="py-2">Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {position_valuations.map((position) => (
                    <tr key={position.position_valuation_id} className="border-b border-border last:border-0">
                      <td className="py-2 pr-4 font-medium text-slate-900">
                        <TickerLabel securityId={position.security_id} />
                      </td>
                      <td className="py-2 pr-4">{position.quantity}</td>
                      <td className="py-2 pr-4">{formatCurrency(position.market_value)}</td>
                      <td className={`py-2 pr-4 ${position.unrealized_pnl >= 0 ? "text-success" : "text-danger"}`}>
                        {formatCurrency(position.unrealized_pnl)}
                      </td>
                      <td className="py-2">{formatPercentage(position.portfolio_weight)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {latest_risk_assessment ? (
          <Card>
            <CardHeader>
              <CardTitle>Risk assessment</CardTitle>
            </CardHeader>
            <Badge tone={latest_risk_assessment.risk_level === "HIGH" || latest_risk_assessment.risk_level === "VERY_HIGH" ? "warning" : "neutral"}>
              {latest_risk_assessment.risk_level}
            </Badge>
            <p className="mt-2 text-sm text-slate-800">{latest_risk_assessment.summary}</p>
            {latest_risk_assessment.educational_feedback.length > 0 ? (
              <ul className="mt-3 list-inside list-disc text-sm text-slate-700">
                {latest_risk_assessment.educational_feedback.map((feedback) => (
                  <li key={feedback}>{feedback}</li>
                ))}
              </ul>
            ) : null}
          </Card>
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle>Recent transactions</CardTitle>
          </CardHeader>
          {recent_transactions.length === 0 ? (
            <EmptyState title="No transactions yet" />
          ) : (
            <ul className="flex flex-col divide-y divide-border text-sm">
              {recent_transactions.map((transaction) => (
                <li key={transaction.transaction_id} className="flex items-center justify-between py-2">
                  <div>
                    <span className="font-medium text-slate-900">{transaction.transaction_type}</span>{" "}
                    <TickerLabel securityId={transaction.security_id} />
                    <span className="ml-2 text-xs text-muted">{formatDateTime(transaction.requested_at)}</span>
                  </div>
                  <Badge tone={transaction.status === "EXECUTED" ? "success" : transaction.status === "REJECTED" ? "danger" : "neutral"}>
                    {transaction.status}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent journal entries</CardTitle>
          </CardHeader>
          {recent_journal_entries.length === 0 ? (
            <EmptyState title="No journal entries yet" />
          ) : (
            <ul className="flex flex-col divide-y divide-border text-sm">
              {recent_journal_entries.map((entry) => (
                <li key={entry.journal_entry_id} className="py-2">
                  <div className="flex items-center gap-2">
                    <Badge tone="neutral">{entry.action}</Badge>
                    <span className="text-xs text-muted">{formatDateTime(entry.decision_at)}</span>
                  </div>
                  <p className="mt-1 text-slate-700">{entry.rationale}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

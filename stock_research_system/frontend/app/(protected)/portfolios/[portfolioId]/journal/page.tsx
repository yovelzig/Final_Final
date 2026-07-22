"use client";

import { use, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { PageHeading } from "@/components/ui/PageHeading";
import { SelectField } from "@/components/ui/Select";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { TextareaField } from "@/components/ui/Textarea";
import { formatDateTime } from "@/lib/formatting";
import { useJournalEntries, useRecordJournalEntry } from "@/hooks/usePortfolios";
import type { components } from "@/types/generated-api";

/** Standalone (non-trade) journal entries are limited to reflective
 * actions - a BUY/SELL entry is only ever recorded alongside an actual
 * trade execution, never invented here. */
type StandaloneJournalAction = "HOLD" | "REBALANCE" | "RESEARCH_MORE";
type DecisionConfidence = components["schemas"]["DecisionConfidence"];

export default function PortfolioJournalPage({ params }: { params: Promise<{ portfolioId: string }> }) {
  const { portfolioId } = use(params);
  const journalQuery = useJournalEntries(portfolioId);
  const recordEntry = useRecordJournalEntry(portfolioId);

  const [ticker, setTicker] = useState("");
  const [action, setAction] = useState<StandaloneJournalAction>("HOLD");
  const [rationale, setRationale] = useState("");
  const [confidence, setConfidence] = useState<DecisionConfidence>("MEDIUM");

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!rationale.trim()) return;
    recordEntry.mutate(
      {
        ticker: ticker.trim() ? ticker.trim().toUpperCase() : null,
        action,
        decision_at: new Date().toISOString(),
        rationale,
        confidence,
      },
      {
        onSuccess: () => {
          setRationale("");
          setTicker("");
        },
      }
    );
  };

  return (
    <div>
      <PageHeading title="Decision journal" description="Record your reasoning even when you don't trade." />

      <div className="flex flex-col gap-6">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 rounded-card border border-border bg-surface p-6">
          {recordEntry.isError ? <ErrorState error={recordEntry.error} /> : null}

          <SelectField label="Decision" value={action} onChange={(event) => setAction(event.target.value as StandaloneJournalAction)}>
            <option value="HOLD">Hold</option>
            <option value="REBALANCE">Rebalance</option>
            <option value="RESEARCH_MORE">Research more</option>
          </SelectField>
          <FormField
            label="Ticker (optional)"
            value={ticker}
            onChange={(event) => setTicker(event.target.value.toUpperCase())}
            placeholder="Leave blank for a portfolio-wide note"
          />
          <TextareaField
            label="Your reasoning"
            value={rationale}
            onChange={(event) => setRationale(event.target.value)}
            rows={3}
            required
          />
          <SelectField label="Confidence" value={confidence} onChange={(event) => setConfidence(event.target.value as DecisionConfidence)}>
            <option value="VERY_LOW">Very low</option>
            <option value="LOW">Low</option>
            <option value="MEDIUM">Medium</option>
            <option value="HIGH">High</option>
            <option value="VERY_HIGH">Very high</option>
          </SelectField>

          <Button type="submit" isLoading={recordEntry.isPending} disabled={!rationale.trim()} className="self-start">
            Add journal entry
          </Button>
        </form>

        {journalQuery.isPending ? (
          <LoadingSkeletonCard />
        ) : journalQuery.isError ? (
          <ErrorState error={journalQuery.error} onRetry={() => void journalQuery.refetch()} />
        ) : journalQuery.data.length === 0 ? (
          <EmptyState title="No journal entries yet" />
        ) : (
          <ul className="flex flex-col divide-y divide-border rounded-card border border-border bg-surface px-6">
            {journalQuery.data.map((entry) => (
              <li key={entry.journal_entry_id} className="py-4">
                <div className="flex items-center gap-2">
                  <Badge tone="neutral">{entry.action}</Badge>
                  <span className="text-xs text-muted">{formatDateTime(entry.decision_at)}</span>
                </div>
                <p className="mt-1 text-sm text-slate-700">{entry.rationale}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { PageHeading } from "@/components/ui/PageHeading";
import { useCreatePortfolio } from "@/hooks/usePortfolios";

export default function NewPortfolioPage() {
  const router = useRouter();
  const createPortfolio = useCreatePortfolio();

  const [name, setName] = useState("");
  const [initialCash, setInitialCash] = useState("10000");
  const [benchmarkTicker, setBenchmarkTicker] = useState("");
  const [allowFractionalShares, setAllowFractionalShares] = useState(true);
  const [requireDecisionJournal, setRequireDecisionJournal] = useState(true);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const cash = Number(initialCash);
    if (!name.trim() || !Number.isFinite(cash) || cash <= 0) return;
    createPortfolio.mutate(
      {
        name: name.trim(),
        initial_cash: cash,
        simulation_start_at: new Date().toISOString(),
        benchmark_ticker: benchmarkTicker.trim() || null,
        allow_fractional_shares: allowFractionalShares,
        require_decision_journal: requireDecisionJournal,
        fixed_transaction_fee: 0,
        transaction_fee_bps: 0,
      },
      { onSuccess: (portfolio) => router.push(`/portfolios/${portfolio.portfolio_id}`) }
    );
  };

  return (
    <div>
      <PageHeading title="New portfolio" description="Set up a virtual portfolio to practice with." />

      <form onSubmit={handleSubmit} className="flex max-w-md flex-col gap-4 rounded-card border border-border bg-surface p-6">
        {createPortfolio.isError ? <ErrorState error={createPortfolio.error} /> : null}

        <FormField label="Portfolio name" value={name} onChange={(event) => setName(event.target.value)} required />
        <FormField
          label="Starting cash (USD)"
          type="number"
          min={1}
          step="0.01"
          value={initialCash}
          onChange={(event) => setInitialCash(event.target.value)}
          required
        />
        <FormField
          label="Benchmark ticker (optional)"
          placeholder="e.g. SPY"
          value={benchmarkTicker}
          onChange={(event) => setBenchmarkTicker(event.target.value.toUpperCase())}
        />

        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={allowFractionalShares}
            onChange={(event) => setAllowFractionalShares(event.target.checked)}
            className="h-4 w-4 accent-[#2D5BFF]"
          />
          Allow fractional shares
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={requireDecisionJournal}
            onChange={(event) => setRequireDecisionJournal(event.target.checked)}
            className="h-4 w-4 accent-[#2D5BFF]"
          />
          Require a decision journal entry with every trade
        </label>

        <Button type="submit" isLoading={createPortfolio.isPending} className="mt-2">
          Create portfolio
        </Button>
      </form>
    </div>
  );
}

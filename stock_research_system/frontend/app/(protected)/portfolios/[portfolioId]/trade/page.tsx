"use client";

import { use, useState } from "react";
import { useRouter } from "next/navigation";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { PageHeading } from "@/components/ui/PageHeading";
import { SelectField } from "@/components/ui/Select";
import { TextareaField } from "@/components/ui/Textarea";
import { formatCurrency } from "@/lib/formatting";
import { buildTradeFingerprint, useIdempotencyKey } from "@/hooks/useIdempotencyKey";
import { useExecuteTrade, usePreviewTrade } from "@/hooks/usePortfolios";
import type { components } from "@/types/generated-api";
import type { TradePreviewResponse } from "@/types/api-schemas";

type PortfolioTransactionType = components["schemas"]["PortfolioTransactionType"];
type DecisionConfidence = components["schemas"]["DecisionConfidence"];

export default function TradePage({ params }: { params: Promise<{ portfolioId: string }> }) {
  const { portfolioId } = use(params);
  const router = useRouter();

  const [ticker, setTicker] = useState("");
  const [transactionType, setTransactionType] = useState<PortfolioTransactionType>("BUY");
  const [quantity, setQuantity] = useState("1");
  const [rationale, setRationale] = useState("");
  const [confidence, setConfidence] = useState<DecisionConfidence>("MEDIUM");
  const [includeJournalEntry, setIncludeJournalEntry] = useState(true);

  const [requestedAt, setRequestedAt] = useState<string | null>(null);
  const [preview, setPreview] = useState<TradePreviewResponse | null>(null);

  const previewTrade = usePreviewTrade(portfolioId);
  const executeTrade = useExecuteTrade(portfolioId);

  const fingerprint = buildTradeFingerprint({
    portfolioId,
    ticker: ticker.trim().toUpperCase(),
    transactionType,
    quantity: Number(quantity) || 0,
    requestedAt: requestedAt ?? "",
  });
  const idempotencyKey = useIdempotencyKey(fingerprint);

  const handlePreview = (event: React.FormEvent) => {
    event.preventDefault();
    const qty = Number(quantity);
    if (!ticker.trim() || !Number.isFinite(qty) || qty <= 0) return;
    const now = new Date().toISOString();
    setRequestedAt(now);
    previewTrade.mutate(
      { ticker: ticker.trim().toUpperCase(), transaction_type: transactionType, quantity: qty, requested_at: now },
      { onSuccess: (data) => setPreview(data) }
    );
  };

  const handleConfirm = () => {
    if (!preview || !requestedAt) return;
    executeTrade.mutate(
      {
        idempotencyKey,
        body: {
          ticker: preview.ticker,
          transaction_type: preview.transaction_type,
          quantity: preview.requested_quantity,
          requested_at: requestedAt,
          journal_entry: includeJournalEntry
            ? {
                action: preview.transaction_type,
                decision_at: requestedAt,
                rationale,
                confidence,
              }
            : null,
        },
      },
      { onSuccess: () => router.push(`/portfolios/${portfolioId}`) }
    );
  };

  const handleChangeTradeInputs = () => {
    setPreview(null);
    setRequestedAt(null);
  };

  return (
    <div>
      <PageHeading title="Trade" description="Preview a trade before you confirm it." />

      {!preview ? (
        <form
          onSubmit={handlePreview}
          className="flex max-w-md flex-col gap-4 rounded-card border border-border bg-surface p-6"
        >
          {previewTrade.isError ? <ErrorState error={previewTrade.error} /> : null}

          <FormField
            label="Ticker"
            value={ticker}
            onChange={(event) => {
              handleChangeTradeInputs();
              setTicker(event.target.value.toUpperCase());
            }}
            required
          />
          <SelectField
            label="Action"
            value={transactionType}
            onChange={(event) => {
              handleChangeTradeInputs();
              setTransactionType(event.target.value as PortfolioTransactionType);
            }}
          >
            <option value="BUY">Buy</option>
            <option value="SELL">Sell</option>
          </SelectField>
          <FormField
            label="Quantity"
            type="number"
            min={0.0001}
            step="any"
            value={quantity}
            onChange={(event) => {
              handleChangeTradeInputs();
              setQuantity(event.target.value);
            }}
            required
          />

          <Button type="submit" isLoading={previewTrade.isPending}>
            Preview trade
          </Button>
        </form>
      ) : (
        <div className="flex max-w-md flex-col gap-4 rounded-card border border-border bg-surface p-6">
          <h2 className="text-base font-semibold text-slate-900">
            {preview.transaction_type} {preview.requested_quantity} {preview.ticker}
          </h2>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-xs text-muted">Expected price</dt>
              <dd className="font-medium text-slate-900">{formatCurrency(preview.expected_execution_price)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Estimated fee</dt>
              <dd className="font-medium text-slate-900">{formatCurrency(preview.estimated_fee)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Cash before</dt>
              <dd className="font-medium text-slate-900">{formatCurrency(preview.cash_before)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Cash after</dt>
              <dd className="font-medium text-slate-900">{formatCurrency(preview.cash_after)}</dd>
            </div>
          </dl>

          {preview.warnings.length > 0 ? (
            <Alert tone="warning">
              <ul className="list-inside list-disc">
                {preview.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </Alert>
          ) : null}

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={includeJournalEntry}
              onChange={(event) => setIncludeJournalEntry(event.target.checked)}
              className="h-4 w-4 accent-[#2D5BFF]"
            />
            Record a decision journal entry with this trade
          </label>

          {includeJournalEntry ? (
            <>
              <TextareaField
                label="Why are you making this trade?"
                value={rationale}
                onChange={(event) => setRationale(event.target.value)}
                rows={3}
              />
              <SelectField label="Confidence" value={confidence} onChange={(event) => setConfidence(event.target.value as DecisionConfidence)}>
                <option value="VERY_LOW">Very low</option>
                <option value="LOW">Low</option>
                <option value="MEDIUM">Medium</option>
                <option value="HIGH">High</option>
                <option value="VERY_HIGH">Very high</option>
              </SelectField>
            </>
          ) : null}

          {executeTrade.isError ? <ErrorState error={executeTrade.error} onRetry={handleConfirm} /> : null}

          <div className="flex gap-2">
            <Button
              onClick={handleConfirm}
              isLoading={executeTrade.isPending}
              disabled={includeJournalEntry && rationale.trim().length === 0}
            >
              Confirm trade
            </Button>
            <Button variant="ghost" onClick={handleChangeTradeInputs} disabled={executeTrade.isPending}>
              Change trade
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

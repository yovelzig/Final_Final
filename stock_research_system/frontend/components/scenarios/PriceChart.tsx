"use client";

import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatCurrency, formatDate } from "@/lib/formatting";
import type { ScenarioChartPointResponse } from "@/types/api-schemas";

/** Renders a close-price line chart for a scenario window. Always
 * pass exactly the points the caller has determined are safe to show
 * (observation-only for the pre-decision view, or the future window
 * only after an explicit reveal) - this component does not know or
 * enforce that boundary itself. */
export function PriceChart({
  points,
  label,
  color = "#2D5BFF",
}: {
  points: ScenarioChartPointResponse[];
  label: string;
  color?: string;
}) {
  if (points.length === 0) {
    return <p className="text-sm text-muted">No chart data available.</p>;
  }

  const data = points.map((point) => ({ timestamp: point.timestamp, close: point.close }));
  const first = points[0]!;
  const last = points[points.length - 1]!;
  const direction = last.close > first.close ? "rose" : last.close < first.close ? "fell" : "stayed flat";
  const summary = `${label}: ${direction} from ${formatCurrency(first.close)} on ${formatDate(first.timestamp)} to ${formatCurrency(last.close)} on ${formatDate(last.timestamp)}.`;

  return (
    <div>
      <p className="sr-only">{summary}</p>
      <div aria-hidden="true" style={{ width: "100%", height: 220 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
            <XAxis
              dataKey="timestamp"
              tickFormatter={(value: string) => formatDate(value)}
              tick={{ fontSize: 11 }}
              minTickGap={30}
            />
            <YAxis
              domain={["auto", "auto"]}
              tickFormatter={(value: number) => formatCurrency(value)}
              tick={{ fontSize: 11 }}
              width={70}
            />
            <Tooltip
              formatter={(value: number) => formatCurrency(value)}
              labelFormatter={(value: string) => formatDate(value)}
            />
            <Line type="monotone" dataKey="close" stroke={color} dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-xs text-muted">{summary}</p>
    </div>
  );
}

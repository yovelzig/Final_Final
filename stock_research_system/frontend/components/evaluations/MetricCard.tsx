import { Card, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

/** One metric's summary tile - always paired with a plain-text
 * description of pass/fail so screen-reader users get the same
 * information sighted users get from color alone. */
export function MetricCard({
  name,
  score,
  passed,
  isHardGate,
}: {
  name: string;
  score: number | null;
  passed: boolean | null;
  isHardGate?: boolean;
}) {
  const formatted = score === null ? "-" : score.toFixed(3);
  const tone = passed === false ? "danger" : passed === true ? "success" : "neutral";
  const statusText = passed === false ? "failing" : passed === true ? "passing" : "not evaluated";

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-sm">{name.replace(/_/g, " ")}</CardTitle>
        {isHardGate ? <Badge tone="primary">hard gate</Badge> : null}
      </CardHeader>
      <p className="text-2xl font-bold text-slate-900">{formatted}</p>
      <p className="text-sm text-muted">
        <Badge tone={tone}>{statusText}</Badge>
      </p>
    </Card>
  );
}

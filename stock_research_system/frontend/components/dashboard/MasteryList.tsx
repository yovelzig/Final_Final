import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Ltr } from "@/components/ui/Ltr";
import { useDictionary } from "@/providers/LocaleProvider";
import type { SkillMasteryResponse } from "@/types/api-schemas";

const MASTERY_TONE: Record<SkillMasteryResponse["mastery_level"], BadgeTone> = {
  NOT_ASSESSED: "neutral",
  NOVICE: "warning",
  DEVELOPING: "primary",
  PROFICIENT: "primary",
  MASTERED: "success",
};

export function MasteryList({ items }: { items: SkillMasteryResponse[] }) {
  const t = useDictionary();

  if (items.length === 0) {
    return <EmptyState title={t.dashboard.mastery.emptyTitle} description={t.dashboard.mastery.emptyDescription} />;
  }

  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <li key={item.skill_id} className="flex items-center justify-between rounded-lg border border-border px-3 py-2.5">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-800">
              {t.dashboard.mastery.skillLabel} <Ltr>{item.skill_id.slice(0, 8)}</Ltr>
            </span>
            <Badge tone={MASTERY_TONE[item.mastery_level]}>{t.dashboard.mastery.levels[item.mastery_level]}</Badge>
          </div>
          <span className="text-xs text-muted">
            <Ltr>{Math.round(item.mastery_score * 100)}%</Ltr>
          </span>
        </li>
      ))}
    </ul>
  );
}

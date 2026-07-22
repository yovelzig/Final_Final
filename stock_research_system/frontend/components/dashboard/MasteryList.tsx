import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import type { SkillMasteryResponse } from "@/types/api-schemas";

const MASTERY_LABEL: Record<SkillMasteryResponse["mastery_level"], string> = {
  NOT_ASSESSED: "Not assessed",
  NOVICE: "Novice",
  DEVELOPING: "Developing",
  PROFICIENT: "Proficient",
  MASTERED: "Mastered",
};

const MASTERY_TONE: Record<SkillMasteryResponse["mastery_level"], BadgeTone> = {
  NOT_ASSESSED: "neutral",
  NOVICE: "warning",
  DEVELOPING: "primary",
  PROFICIENT: "primary",
  MASTERED: "success",
};

export function MasteryList({ items }: { items: SkillMasteryResponse[] }) {
  if (items.length === 0) {
    return (
      <EmptyState
        title="No skills assessed yet"
        description="Complete a lesson or the diagnostic assessment to start building your skill profile."
      />
    );
  }

  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <li key={item.skill_id} className="flex items-center justify-between rounded-lg border border-border px-3 py-2.5">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-800">Skill {item.skill_id.slice(0, 8)}</span>
            <Badge tone={MASTERY_TONE[item.mastery_level]}>{MASTERY_LABEL[item.mastery_level]}</Badge>
          </div>
          <span className="text-xs text-muted">{Math.round(item.mastery_score * 100)}%</span>
        </li>
      ))}
    </ul>
  );
}

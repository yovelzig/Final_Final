"use client";

import { useId } from "react";

import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Ltr } from "@/components/ui/Ltr";
import type { Dictionary } from "@/lib/i18n/types";
import { useDictionary } from "@/providers/LocaleProvider";
import type { MasteryLevel, SkillMasteryResponse } from "@/types/api-schemas";

type FinancialSkillsCopy = Dictionary["dashboard"]["financialSkills"];

const LEVEL_TONE: Record<MasteryLevel, BadgeTone> = {
  NOT_ASSESSED: "neutral",
  NOVICE: "warning",
  DEVELOPING: "primary",
  PROFICIENT: "primary",
  MASTERED: "success",
};

/** Matches each row's badge tone, so the bar reinforces the written
 * status instead of being the only thing that carries it. */
const LEVEL_FILL: Record<MasteryLevel, string> = {
  NOT_ASSESSED: "bg-slate-400",
  NOVICE: "bg-warning",
  DEVELOPING: "bg-primary",
  PROFICIENT: "bg-primary",
  MASTERED: "bg-success",
};

/**
 * The canonical name comes from `financial_skills` via the API. Hebrew (and
 * any future locale) translates it through a code-keyed dictionary; an
 * unlisted or brand-new code keeps the backend's English name, and only a
 * skill with no metadata at all reaches the localized placeholder. A
 * `skill_id` is never a name.
 */
function resolveSkillName(item: SkillMasteryResponse, copy: FinancialSkillsCopy): string {
  const localizedNames: Partial<Record<string, string>> = copy.skillNames;
  const localized = item.skill_code ? localizedNames[item.skill_code] : undefined;
  return localized || item.skill_name || copy.fallbackSkillName;
}

function toPercent(masteryScore: number): number {
  return Math.round(Math.min(1, Math.max(0, masteryScore)) * 100);
}

function FinancialSkillRow({ item, copy }: { item: SkillMasteryResponse; copy: FinancialSkillsCopy }) {
  const nameId = useId();
  const name = resolveSkillName(item, copy);
  const percent = toPercent(item.mastery_score);

  return (
    <li className="flex flex-col gap-2 py-3.5 first:pt-0 last:pb-0">
      <div className="flex items-baseline justify-between gap-3">
        <span id={nameId} className="min-w-0 break-words text-sm font-medium text-slate-800">
          {name}
        </span>
        {/* The progressbar below already announces this number. */}
        <span aria-hidden="true" className="shrink-0 text-sm font-semibold tabular-nums text-slate-900">
          <Ltr>{percent}%</Ltr>
        </span>
      </div>
      <div>
        <Badge tone={LEVEL_TONE[item.mastery_level]}>{copy.levels[item.mastery_level]}</Badge>
      </div>
      <div
        role="progressbar"
        aria-labelledby={nameId}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="h-2 w-full overflow-hidden rounded-full bg-slate-100"
      >
        <div
          className={`h-full rounded-full transition-[width] ${LEVEL_FILL[item.mastery_level]}`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </li>
  );
}

export function FinancialSkillsProgress({ items }: { items: SkillMasteryResponse[] }) {
  const t = useDictionary();
  const copy = t.dashboard.financialSkills;

  if (items.length === 0) {
    return <EmptyState title={copy.emptyTitle} description={copy.emptyDescription} />;
  }

  return (
    <ul className="flex flex-col divide-y divide-border">
      {items.map((item) => (
        <FinancialSkillRow key={item.skill_id} item={item} copy={copy} />
      ))}
    </ul>
  );
}

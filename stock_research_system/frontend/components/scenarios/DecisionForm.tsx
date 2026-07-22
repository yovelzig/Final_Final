"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { SelectField } from "@/components/ui/Select";
import { TextareaField } from "@/components/ui/Textarea";
import type { components } from "@/types/generated-api";
import type { ScenarioOptionResponse } from "@/types/api-schemas";

type ConfidenceLevel = components["schemas"]["ConfidenceLevel"];

const CONFIDENCE_OPTIONS: { value: ConfidenceLevel; label: string }[] = [
  { value: "VERY_LOW", label: "Very low" },
  { value: "LOW", label: "Low" },
  { value: "MEDIUM", label: "Medium" },
  { value: "HIGH", label: "High" },
  { value: "VERY_HIGH", label: "Very high" },
];

export function DecisionForm({
  options,
  onSubmit,
  isSubmitting,
}: {
  options: ScenarioOptionResponse[];
  onSubmit: (input: { selectedOptionId: string; confidenceLevel: ConfidenceLevel | null; rationale: string }) => void;
  isSubmitting: boolean;
}) {
  const [selectedOptionId, setSelectedOptionId] = useState<string | null>(null);
  const [confidenceLevel, setConfidenceLevel] = useState<ConfidenceLevel | "">("");
  const [rationale, setRationale] = useState("");

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedOptionId) return;
    onSubmit({
      selectedOptionId,
      confidenceLevel: confidenceLevel === "" ? null : confidenceLevel,
      rationale,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium text-slate-700">Your decision</legend>
        {options.map((option) => (
          <label
            key={option.option_id}
            className={`flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors ${
              selectedOptionId === option.option_id ? "border-primary bg-primary-light" : "border-border hover:bg-slate-50"
            } ${isSubmitting ? "cursor-not-allowed opacity-70" : ""}`}
          >
            <input
              type="radio"
              name="scenario-decision"
              value={option.option_id}
              checked={selectedOptionId === option.option_id}
              disabled={isSubmitting}
              onChange={() => setSelectedOptionId(option.option_id)}
              className="mt-0.5 h-4 w-4 accent-[#2D5BFF]"
            />
            <span className="text-slate-800">{option.content}</span>
          </label>
        ))}
      </fieldset>

      <SelectField
        label="How confident are you? (optional)"
        value={confidenceLevel}
        onChange={(event) => setConfidenceLevel(event.target.value as ConfidenceLevel | "")}
        disabled={isSubmitting}
      >
        <option value="">Prefer not to say</option>
        {CONFIDENCE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </SelectField>

      <TextareaField
        label="Why did you make this decision? (optional)"
        value={rationale}
        onChange={(event) => setRationale(event.target.value)}
        disabled={isSubmitting}
        rows={3}
        hint="Your reasoning helps you reflect - it isn't graded."
      />

      <Button type="submit" disabled={!selectedOptionId} isLoading={isSubmitting} className="self-start">
        Submit decision
      </Button>
    </form>
  );
}

import { describe, expect, it } from "vitest";

import { EMPTY_DRAFT } from "@/components/exercises/types";
import { buildAnswerPayload, isAnswerDraftComplete } from "@/hooks/useExerciseDraft";

describe("buildAnswerPayload", () => {
  it("serializes a single-choice answer as selected_option_ids", () => {
    const draft = { ...EMPTY_DRAFT, selectedOptionIds: ["opt-1"] };
    expect(buildAnswerPayload("SINGLE_CHOICE", draft)).toEqual({ selected_option_ids: ["opt-1"] });
  });

  it("serializes a multiple-choice answer with several selections", () => {
    const draft = { ...EMPTY_DRAFT, selectedOptionIds: ["opt-1", "opt-2"] };
    expect(buildAnswerPayload("MULTIPLE_CHOICE", draft)).toEqual({ selected_option_ids: ["opt-1", "opt-2"] });
  });

  it("serializes a numeric answer using locale-safe parsing", () => {
    const draft = { ...EMPTY_DRAFT, numericAnswer: "1,234.5" };
    expect(buildAnswerPayload("NUMERIC_INPUT", draft)).toEqual({ numeric_answer: 1234.5 });
  });

  it("serializes an invalid numeric answer as null rather than NaN", () => {
    const draft = { ...EMPTY_DRAFT, numericAnswer: "not a number" };
    expect(buildAnswerPayload("NUMERIC_INPUT", draft)).toEqual({ numeric_answer: null });
  });

  it("serializes an ordering answer as ordered_option_ids", () => {
    const draft = { ...EMPTY_DRAFT, orderedOptionIds: ["opt-2", "opt-1"] };
    expect(buildAnswerPayload("ORDERING", draft)).toEqual({ ordered_option_ids: ["opt-2", "opt-1"] });
  });

  it("serializes a text response as text_answer", () => {
    const draft = { ...EMPTY_DRAFT, textAnswer: "My reasoning" };
    expect(buildAnswerPayload("TEXT_RESPONSE", draft)).toEqual({ text_answer: "My reasoning" });
  });

  it("never includes an is_correct or score field regardless of exercise type", () => {
    const draft = { ...EMPTY_DRAFT, selectedOptionIds: ["opt-1"] };
    const payload = buildAnswerPayload("SCENARIO_DECISION", draft);
    expect(payload).not.toHaveProperty("is_correct");
    expect(payload).not.toHaveProperty("score");
  });
});

describe("isAnswerDraftComplete", () => {
  it("requires exactly one selection for single-select types", () => {
    expect(isAnswerDraftComplete("SINGLE_CHOICE", EMPTY_DRAFT)).toBe(false);
    expect(isAnswerDraftComplete("SINGLE_CHOICE", { ...EMPTY_DRAFT, selectedOptionIds: ["a"] })).toBe(true);
    expect(isAnswerDraftComplete("SINGLE_CHOICE", { ...EMPTY_DRAFT, selectedOptionIds: ["a", "b"] })).toBe(false);
  });

  it("requires at least one selection for multiple-choice, without revealing an expected count", () => {
    expect(isAnswerDraftComplete("MULTIPLE_CHOICE", EMPTY_DRAFT)).toBe(false);
    expect(isAnswerDraftComplete("MULTIPLE_CHOICE", { ...EMPTY_DRAFT, selectedOptionIds: ["a"] })).toBe(true);
  });

  it("requires a parseable numeric value", () => {
    expect(isAnswerDraftComplete("NUMERIC_INPUT", EMPTY_DRAFT)).toBe(false);
    expect(isAnswerDraftComplete("NUMERIC_INPUT", { ...EMPTY_DRAFT, numericAnswer: "abc" })).toBe(false);
    expect(isAnswerDraftComplete("NUMERIC_INPUT", { ...EMPTY_DRAFT, numericAnswer: "42" })).toBe(true);
  });

  it("requires at least one ordered item", () => {
    expect(isAnswerDraftComplete("ORDERING", EMPTY_DRAFT)).toBe(false);
    expect(isAnswerDraftComplete("ORDERING", { ...EMPTY_DRAFT, orderedOptionIds: ["a"] })).toBe(true);
  });

  it("requires non-whitespace text for a text response", () => {
    expect(isAnswerDraftComplete("TEXT_RESPONSE", EMPTY_DRAFT)).toBe(false);
    expect(isAnswerDraftComplete("TEXT_RESPONSE", { ...EMPTY_DRAFT, textAnswer: "   " })).toBe(false);
    expect(isAnswerDraftComplete("TEXT_RESPONSE", { ...EMPTY_DRAFT, textAnswer: "hello" })).toBe(true);
  });
});

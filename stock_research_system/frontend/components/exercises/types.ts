export interface AnswerDraft {
  selectedOptionIds: string[];
  orderedOptionIds: string[];
  numericAnswer: string;
  textAnswer: string;
}

export const EMPTY_DRAFT: AnswerDraft = {
  selectedOptionIds: [],
  orderedOptionIds: [],
  numericAnswer: "",
  textAnswer: "",
};

export interface ExerciseInputProps {
  options: { option_id: string; option_key: string; content: string; position: number }[];
  draft: AnswerDraft;
  onChange: (draft: AnswerDraft) => void;
  disabled: boolean;
}

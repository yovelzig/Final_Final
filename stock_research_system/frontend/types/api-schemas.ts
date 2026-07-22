/**
 * Convenience re-exports of frequently used generated schema types.
 * Always read from `components["schemas"]` in `generated-api.ts` -
 * never hand-declare a shape that duplicates what the backend already
 * publishes, so a backend field rename is caught by `tsc` here instead
 * of silently drifting.
 */
import type { components } from "@/types/generated-api";

export type LoginRequest = components["schemas"]["LoginRequest"];
export type LoginResponse = components["schemas"]["LoginResponse"];
export type RegisterRequest = components["schemas"]["RegisterRequest"];
export type RegisterResponse = components["schemas"]["RegisterResponse"];
export type RefreshRequest = components["schemas"]["RefreshRequest"];
export type TokenPairResponse = components["schemas"]["TokenPairResponse"];
export type LogoutRequest = components["schemas"]["LogoutRequest"];
export type LogoutAllResponse = components["schemas"]["LogoutAllResponse"];
export type MeResponse = components["schemas"]["MeResponse"];

export type LearnerProfileResponse = components["schemas"]["LearnerProfileResponse"];
export type LearnerUpdateRequest = components["schemas"]["LearnerUpdateRequest"];
export type DashboardResponse = components["schemas"]["DashboardResponse"];
export type SkillMasteryResponse = components["schemas"]["SkillMasteryResponse"];
export type ProgressResponse = components["schemas"]["ProgressResponse"];
export type MisconceptionResponse = components["schemas"]["MisconceptionResponse"];
export type PaginatedSkillMasteryResponse = components["schemas"]["PaginatedResponse_SkillMasteryResponse_"];
export type PaginatedProgressResponse = components["schemas"]["PaginatedResponse_ProgressResponse_"];
export type PaginatedMisconceptionResponse = components["schemas"]["PaginatedResponse_MisconceptionResponse_"];

export type LearningPathResponse = components["schemas"]["LearningPathResponse"];
export type LearningModuleResponse = components["schemas"]["LearningModuleResponse"];
export type LessonResponse = components["schemas"]["LessonResponse"];
export type ExerciseResponse = components["schemas"]["ExerciseResponse"];
export type ExerciseOptionResponse = components["schemas"]["ExerciseOptionResponse"];
export type AttemptResponse = components["schemas"]["AttemptResponse"];
export type SubmitAnswerRequest = components["schemas"]["SubmitAnswerRequest"];
export type SubmitAnswerResponse = components["schemas"]["SubmitAnswerResponse"];
export type StartAttemptRequest = components["schemas"]["StartAttemptRequest"];

export type LearningSessionResponse = components["schemas"]["LearningSessionResponse"];
export type ExerciseRecommendationResponse = components["schemas"]["ExerciseRecommendationResponse"];
export type AdaptiveDecisionResponse = components["schemas"]["AdaptiveDecisionResponse"];
export type SessionSummaryResponse = components["schemas"]["SessionSummaryResponse"];
export type StartSessionRequest = components["schemas"]["StartSessionRequest"];
export type StartRecommendedExerciseRequest = components["schemas"]["StartRecommendedExerciseRequest"];
export type SubmitDecisionAnswerRequest = components["schemas"]["SubmitDecisionAnswerRequest"];

export type StartDiagnosticRequest = components["schemas"]["StartDiagnosticRequest"];
export type DiagnosticSummaryResponse = components["schemas"]["DiagnosticSummaryResponse"];
export type DiagnosticStatusResponse = components["schemas"]["DiagnosticStatusResponse"];
export type DiagnosticItemResponse = components["schemas"]["DiagnosticItemResponse"];
export type StartDiagnosticItemRequest = components["schemas"]["StartDiagnosticItemRequest"];
export type SubmitDiagnosticResultRequest = components["schemas"]["SubmitDiagnosticResultRequest"];

export type ScenarioCatalogItemResponse = components["schemas"]["ScenarioCatalogItemResponse"];
export type LearnerScenarioResponse = components["schemas"]["LearnerScenarioResponse"];
export type ScenarioSubmissionResponse = components["schemas"]["ScenarioSubmissionResponse"];
export type ScenarioRevealResponse = components["schemas"]["ScenarioRevealResponse"];
export type SubmitDecisionRequest = components["schemas"]["SubmitDecisionRequest"];

export type VirtualPortfolioResponse = components["schemas"]["VirtualPortfolioResponse"];
export type CreatePortfolioRequest = components["schemas"]["CreatePortfolioRequest"];
export type PortfolioOverviewResponse = components["schemas"]["PortfolioOverviewResponse"];
export type PreviewTradeRequest = components["schemas"]["PreviewTradeRequest"];
export type TradePreviewResponse = components["schemas"]["TradePreviewResponse"];
export type ExecuteTradeRequest = components["schemas"]["ExecuteTradeRequest"];
export type TradeExecutionResponse = components["schemas"]["TradeExecutionResponse"];
export type PortfolioTransactionResponse = components["schemas"]["PortfolioTransactionResponse"];
export type PortfolioHoldingResponse = components["schemas"]["PortfolioHoldingResponse"];
export type RecordJournalEntryRequest = components["schemas"]["RecordJournalEntryRequest"];
export type JournalEntryRequest = components["schemas"]["JournalEntryRequest"];
export type JournalEntryResponse = components["schemas"]["JournalEntryResponse"];
export type ValueAsOfRequest = components["schemas"]["ValueAsOfRequest"];
export type PortfolioValuationResultResponse = components["schemas"]["PortfolioValuationResultResponse"];
export type LatestValuationResponse = components["schemas"]["LatestValuationResponse"];
export type PerformanceSummaryResponse = components["schemas"]["PerformanceSummaryResponse"];

export type CreateConversationRequest = components["schemas"]["CreateConversationRequest"];
export type TutorConversationResponse = components["schemas"]["TutorConversationResponse"];
export type TutorMessageResponse = components["schemas"]["TutorMessageResponse"];
export type AskQuestionRequest = components["schemas"]["AskQuestionRequest"];
export type AskResponse = components["schemas"]["AskResponse"];
export type CitationResponse = components["schemas"]["CitationResponse"];

export type HealthResponse = components["schemas"]["HealthResponse"];
export type ReadinessCheck = components["schemas"]["ReadinessCheck"];

export type CreateThreadRequest = components["schemas"]["CreateThreadRequest"];
export type LearningCoachThreadResponse = components["schemas"]["LearningCoachThreadResponse"];
export type LearningCoachThreadListResponse = components["schemas"]["LearningCoachThreadListResponse"];
export type StartRunRequest = components["schemas"]["StartRunRequest"];
export type LearningCoachRunResponse = components["schemas"]["LearningCoachRunResponse"];
export type LearningCoachEventResponse = components["schemas"]["LearningCoachEventResponse"];
export type LearningCoachApprovalRequest = components["schemas"]["LearningCoachApprovalRequest"];

export type PaginationMeta = components["schemas"]["PaginationMeta"];

export type ScenarioChartPointResponse = components["schemas"]["ScenarioChartPointResponse"];
export type ScenarioOptionResponse = components["schemas"]["ScenarioOptionResponse"];
export type ObservationMetricsResponse = components["schemas"]["ObservationMetricsResponse"];
export type SecurityResponse = components["schemas"]["SecurityResponse"];

// -- Phase 13: quality evaluation (admin-only) -----------------------------------------------
export type QualityEvaluationSuiteResponse = components["schemas"]["QualityEvaluationSuiteResponse"];
export type QualityEvaluationSuiteListResponse = components["schemas"]["QualityEvaluationSuiteListResponse"];
export type QualityEvaluationRunResponse = components["schemas"]["QualityEvaluationRunResponse"];
export type QualityEvaluationRunListResponse = components["schemas"]["QualityEvaluationRunListResponse"];
export type QualityEvaluationSampleResultResponse = components["schemas"]["QualityEvaluationSampleResultResponse"];
export type QualityEvaluationSampleResultListResponse = components["schemas"]["QualityEvaluationSampleResultListResponse"];
export type QualityMetricResultResponse = components["schemas"]["QualityMetricResultResponse"];
export type QualityMetricResultListResponse = components["schemas"]["QualityMetricResultListResponse"];
export type QualityEvaluationBaselineResponse = components["schemas"]["QualityEvaluationBaselineResponse"];
export type QualityEvaluationBaselineListResponse = components["schemas"]["QualityEvaluationBaselineListResponse"];
export type CreateRunRequest = components["schemas"]["CreateRunRequest"];
export type CreateRunResponse = components["schemas"]["CreateRunResponse"];
export type ApproveBaselineRequest = components["schemas"]["ApproveBaselineRequest"];
export type CompareRunRequest = components["schemas"]["CompareRunRequest"];
export type EvaluationRegressionReportResponse = components["schemas"]["EvaluationRegressionReportResponse"];
export type MetricComparisonResponse = components["schemas"]["MetricComparisonResponse"];
export type QualityEvaluationRunStatus = components["schemas"]["QualityEvaluationRunStatus"];
export type QualityGateStatus = components["schemas"]["QualityGateStatus"];
export type QualityEvaluationCaseStatus = components["schemas"]["QualityEvaluationCaseStatus"];
export type QualityEvaluationMode = components["schemas"]["QualityEvaluationMode"];

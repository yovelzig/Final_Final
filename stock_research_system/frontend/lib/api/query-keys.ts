/**
 * Stable, hierarchical TanStack Query keys. Grouped by feature so a
 * mutation can invalidate precisely (e.g. `queryKeys.portfolios.detail(id)`)
 * without over-invalidating unrelated data.
 */
export const queryKeys = {
  learner: {
    me: () => ["learner", "me"] as const,
    dashboard: () => ["learner", "dashboard"] as const,
    mastery: () => ["learner", "mastery"] as const,
    progress: () => ["learner", "progress"] as const,
    misconceptions: () => ["learner", "misconceptions"] as const,
  },
  curriculum: {
    paths: () => ["curriculum", "paths"] as const,
    path: (pathId: string) => ["curriculum", "paths", pathId] as const,
    modules: (pathId: string) => ["curriculum", "paths", pathId, "modules"] as const,
    module: (moduleId: string) => ["curriculum", "modules", moduleId] as const,
    lessons: (moduleId: string) => ["curriculum", "modules", moduleId, "lessons"] as const,
    lesson: (lessonId: string) => ["curriculum", "lessons", lessonId] as const,
    exercises: (lessonId: string) => ["curriculum", "lessons", lessonId, "exercises"] as const,
    exercise: (exerciseId: string) => ["curriculum", "exercises", exerciseId] as const,
    attempt: (attemptId: string) => ["curriculum", "attempts", attemptId] as const,
  },
  adaptive: {
    session: (sessionId: string) => ["adaptive", "sessions", sessionId] as const,
    diagnostic: (assessmentId: string) => ["adaptive", "diagnostics", assessmentId] as const,
    activeDiagnostic: () => ["adaptive", "diagnostics", "active"] as const,
  },
  scenarios: {
    list: () => ["scenarios", "list"] as const,
    detail: (scenarioId: string) => ["scenarios", "detail", scenarioId] as const,
    reveal: (submissionId: string) => ["scenarios", "reveal", submissionId] as const,
  },
  portfolios: {
    list: () => ["portfolios", "list"] as const,
    detail: (portfolioId: string) => ["portfolios", "detail", portfolioId] as const,
    transactions: (portfolioId: string) => ["portfolios", "detail", portfolioId, "transactions"] as const,
    holdings: (portfolioId: string) => ["portfolios", "detail", portfolioId, "holdings"] as const,
    journal: (portfolioId: string) => ["portfolios", "detail", portfolioId, "journal"] as const,
    latestValuation: (portfolioId: string) => ["portfolios", "detail", portfolioId, "valuation-latest"] as const,
    performance: (portfolioId: string, startAt: string, endAt: string) =>
      ["portfolios", "detail", portfolioId, "performance", startAt, endAt] as const,
  },
  securities: {
    detail: (securityId: string) => ["securities", securityId] as const,
  },
  tutor: {
    conversations: () => ["tutor", "conversations"] as const,
    conversation: (conversationId: string) => ["tutor", "conversations", conversationId] as const,
    messages: (conversationId: string) => ["tutor", "conversations", conversationId, "messages"] as const,
  },
  coach: {
    threads: () => ["coach", "threads"] as const,
    thread: (threadId: string) => ["coach", "threads", threadId] as const,
    run: (runId: string) => ["coach", "runs", runId] as const,
    runEvents: (runId: string) => ["coach", "runs", runId, "events"] as const,
  },
  evaluations: {
    suites: () => ["evaluations", "suites"] as const,
    runs: () => ["evaluations", "runs"] as const,
    run: (runId: string) => ["evaluations", "runs", runId] as const,
    runSamples: (runId: string) => ["evaluations", "runs", runId, "samples"] as const,
    runMetrics: (runId: string) => ["evaluations", "runs", runId, "metrics"] as const,
  },
} as const;

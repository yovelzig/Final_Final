import type { MasteryLevel } from "@/types/api-schemas";

/**
 * Canonical `financial_skills.code` values the curriculum seeds. Keyed by
 * code, never by `skill_id`, so a translation survives a re-seed and can
 * never be derived from an opaque identifier. A skill whose code is not
 * listed here still renders - it falls back to the canonical English
 * `skill_name` the backend returns.
 */
export type FinancialSkillCode =
  | "MONEY_BASICS"
  | "INFLATION"
  | "COMPOUND_INTEREST"
  | "STOCKS"
  | "BONDS"
  | "FUNDS_AND_ETFS"
  | "RISK_AND_RETURN"
  | "DIVERSIFICATION"
  | "MARKET_INDEXES"
  | "CHART_READING"
  | "LONG_TERM_INVESTING";

/**
 * The single source of truth for every translatable string in the MVP
 * surfaces (landing, auth, app shell, dashboard, tutor, coach, and the
 * shared loading/error/empty states). `en.ts` and `he.ts` are each
 * declared `satisfies Dictionary` - a missing or mistyped key in
 * either file is a compile error, which is what guarantees "no
 * missing translation keys" without a runtime lookup.
 */
export interface Dictionary {
  common: {
    finquest: string;
    loading: string;
    retry: string;
    close: string;
    cancel: string;
    send: string;
    back: string;
    somethingWentWrong: string;
    offline: string;
    sessionExpired: string;
    forbidden: string;
    notFound: string;
    rateLimited: string;
    referenceLabel: string;
    globalErrorDescription: string;
    pageNotFoundTitle: string;
    pageNotFoundDescription: string;
    backToDashboard: string;
    status: {
      ACTIVE: string;
      CLOSED: string;
      ARCHIVED: string;
    };
  };
  language: {
    switcherLabel: string;
    english: string;
    hebrew: string;
  };
  nav: {
    skipToContent: string;
    dashboard: string;
    learn: string;
    practice: string;
    scenarios: string;
    portfolio: string;
    tutor: string;
    coach: string;
    settings: string;
    admin: string;
    primaryNavLabel: string;
    mobileNavLabel: string;
  };
  landing: {
    nav: {
      login: string;
      getStarted: string;
    };
    hero: {
      eyebrow: string;
      title: string;
      subtitle: string;
      primaryCta: string;
      secondaryCta: string;
    };
    preview: {
      caption: string;
      lessonLabel: string;
      lessonTitle: string;
      xpLabel: string;
      streakLabel: string;
      tutorPreviewQuestion: string;
      tutorPreviewAnswer: string;
    };
    sections: {
      learningPath: { eyebrow: string; title: string; description: string };
      adaptive: { eyebrow: string; title: string; description: string };
      tutor: { eyebrow: string; title: string; description: string };
      scenarios: { eyebrow: string; title: string; description: string };
      portfolio: { eyebrow: string; title: string; description: string };
    };
    trust: {
      title: string;
      description: string;
      points: string[];
    };
    finalCta: {
      title: string;
      description: string;
      cta: string;
    };
    footer: {
      tagline: string;
      product: string;
      learn: string;
      tutor: string;
      scenarios: string;
      portfolio: string;
      account: string;
      login: string;
      register: string;
      copyright: string;
    };
  };
  auth: {
    login: {
      title: string;
      email: string;
      password: string;
      submit: string;
      noAccount: string;
      createAccount: string;
      genericError: string;
    };
    register: {
      title: string;
      displayName: string;
      email: string;
      password: string;
      passwordHint: string;
      confirmPassword: string;
      dailyGoal: string;
      submit: string;
      haveAccount: string;
      logIn: string;
      genericError: string;
    };
    passwordShow: string;
    passwordHide: string;
  };
  appShell: {
    unauthorizedTitle: string;
    unauthorizedDescription: string;
    xpLabel: string;
    streakLabel: string;
    profileMenuLabel: string;
    settings: string;
    logOut: string;
  };
  dashboard: {
    welcomeBack: string;
    welcomeGeneric: string;
    subtitle: string;
    continueLearning: {
      title: string;
      cta: string;
      emptyTitle: string;
      emptyDescription: string;
      emptyCta: string;
    };
    progress: {
      title: string;
      description: string;
      lessonsCompleted: string;
      misconceptionsOne: string;
      misconceptionsOther: string;
    };
    financialSkills: {
      title: string;
      description: string;
      emptyTitle: string;
      emptyDescription: string;
      /** Used when a mastery row's skill metadata is missing. Never a
       * `skill_id` - learners are shown a topic, not an identifier. */
      fallbackSkillName: string;
      levels: Record<MasteryLevel, string>;
      skillNames: Record<FinancialSkillCode, string>;
    };
    portfolio: {
      title: string;
      description: string;
      cta: string;
      emptyTitle: string;
      emptyDescription: string;
      emptyCta: string;
      holdingsLabel: string;
    };
    scenarioShortcut: {
      title: string;
      description: string;
      cta: string;
    };
    coachShortcut: {
      title: string;
      description: string;
      cta: string;
    };
  };
  tutor: {
    pageTitle: string;
    pageDescription: string;
    askQuestionCta: string;
    contextLabels: {
      generalEducation: string;
      lessonHelp: string;
      exerciseHelp: string;
      scenarioBeforeDecision: string;
      scenarioAfterReveal: string;
      portfolioExplanation: string;
    };
    closeConversation: string;
    closed: string;
    conversationClosedNotice: string;
    you: string;
    tutorRole: string;
    askLabel: string;
    send: string;
    sourcesLabel: string;
    sourceLabel: string;
    retry: string;
    insufficientEvidence: { title: string; description: string };
    refused: { title: string; description: string };
    contextSafety: {
      beforeDecisionTitle: string;
      beforeDecisionBody: string;
      portfolioTitle: string;
      portfolioBody: string;
    };
    empty: { title: string; description: string };
  };
  coach: {
    pageTitle: string;
    description: string;
    newConversation: string;
    suggestedPrompts: string[];
    emptyTitle: string;
    emptyDescription: string;
    askLabel: string;
    send: string;
    closeConversation: string;
    closed: string;
    conversationClosedNotice: string;
    startPrompt: string;
    approvalNeeded: string;
    approved: string;
    declined: string;
    approve: string;
    notNow: string;
    continueLabel: string;
    researchStarted: string;
    researchWaiting: string;
    researchTimedOut: string;
    researchFailed: string;
  };
  emptyState: {
    genericTitle: string;
    genericDescription: string;
  };
}

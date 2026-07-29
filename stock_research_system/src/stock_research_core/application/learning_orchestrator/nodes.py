"""The parent `finquest-learning-coach` graph's node functions.

Every node does exactly one bounded responsibility (per the Phase 12
topology) and returns only a partial state update - never raw ORM
objects, never a database session, never a secret. Route-specific
subgraph logic (grounded explanation, lesson/exercise/scenario/
portfolio tutoring, adaptive recommendation, practice/diagnostic
actions) lives in `subgraphs.py`; this module is the shared spine:
`initialize_run`, `load_authorized_context`, `evaluate_input_guardrail`,
`build_refusal_response`, `build_fallback_response`, `classify_intent`,
`select_route`, `approval_interrupt`, `execute_action`,
`validate_final_output`, `persist_final_result`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from langgraph.types import interrupt

from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail, more_restrictive_decision
from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.application.exceptions import ResearchModelProviderError, StockResearchError
from stock_research_core.application.language.enums import DetectedLanguage, LocalizedMessageKey
from stock_research_core.application.language.localization import localize
from stock_research_core.application.language.ports import LanguageServicePort
from stock_research_core.application.language.query_preparation import (
    LanguageQueryPreparation,
    detect_request_language,
    prepare_language_query,
    untranslated_preparation,
)
from stock_research_core.application.language.unavailable_language_service import UnavailableLanguageService
from stock_research_core.application.learning_orchestrator.actions import (
    AllowlistedLearningActionExecutor,
    ForbiddenLearningActionError,
)
from stock_research_core.application.learning_orchestrator.current_information_policy import (
    InformationNeed,
    classify_information_need,
)
from stock_research_core.application.learning_orchestrator.ports import LearningContextLoaderPort, LearningIntentClassifierPort
from stock_research_core.application.learning_orchestrator.routing import select_route as pure_select_route
from stock_research_core.application.learning_orchestrator.state import (
    LearningCoachGraphState,
    bounded_list,
    bounded_text,
)
from stock_research_core.application.live_research.cik_resolver_ports import CikResolutionStatus, CikResolverPort
from stock_research_core.application.live_research.citation_verifier import ResearchEvidenceCitationVerifier
from stock_research_core.application.live_research.ports import ResearchModelPort
from stock_research_core.application.live_research.rate_limit_ports import AccountResearchRateLimiterPort
from stock_research_core.application.live_research.synthesis_models import (
    ResearchEvidenceInput,
    ResearchSynthesisRequest,
)
from stock_research_core.application.operations.service import BackgroundJobService
from stock_research_core.application.persistence.ports import UnitOfWorkPort
from stock_research_core.application.shared.text_safety import SharedTextSafetyValidator
from stock_research_core.domain.ai_tutor.enums import (
    TutorContextType, TutorGuardrailAction, TutorMessageRole, TutorRequestCategory,
)
from stock_research_core.domain.ai_tutor.models import TutorGuardrailDecision, TutorMessage
from stock_research_core.domain.learning_orchestrator.enums import (
    APPROVAL_REQUIRED_ACTION_TYPES,
    LearningActionProposalStatus,
    LearningActionType,
    LearningIntent,
    LearningOrchestratorEventType,
    LearningOrchestratorRoute,
)
from stock_research_core.domain.learning_orchestrator.models import LearningActionProposal, LearningOrchestratorEvent
from stock_research_core.domain.live_research.enums import EvidenceClassification, ResearchScope
from stock_research_core.domain.operations.enums import BackgroundJobStatus, BackgroundJobType, JobTriggerSource

_ROUTE_LABELS: dict[str, str] = {
    "load_authorized_context": "Loading your learning context",
    "evaluate_input_guardrail": "Checking your question",
    "classify_intent": "Understanding what you're asking",
    LearningOrchestratorRoute.GROUNDED_EXPLANATION.value: "Looking up approved FinQuest material",
    LearningOrchestratorRoute.LESSON_TUTOR.value: "Reviewing this lesson",
    LearningOrchestratorRoute.EXERCISE_TUTOR.value: "Reviewing this exercise",
    LearningOrchestratorRoute.PROGRESS_REFLECTION.value: "Reviewing your learning progress",
    LearningOrchestratorRoute.ADAPTIVE_RECOMMENDATION.value: "Finding what to study next",
    LearningOrchestratorRoute.PRACTICE_ACTION.value: "Preparing a practice session",
    LearningOrchestratorRoute.DIAGNOSTIC_ACTION.value: "Preparing a diagnostic assessment",
    LearningOrchestratorRoute.SCENARIO_BEFORE_TUTOR.value: "Reviewing the scenario so far",
    LearningOrchestratorRoute.SCENARIO_AFTER_TUTOR.value: "Reviewing the scenario outcome",
    LearningOrchestratorRoute.PORTFOLIO_TUTOR.value: "Reviewing your portfolio",
}

_ACTION_PARAMETER_BUILDERS_CONTEXT_KEY: dict[LearningActionType, str] = {
    LearningActionType.OPEN_LESSON: "lesson_id",
    LearningActionType.OPEN_SCENARIO: "scenario_id",
    LearningActionType.OPEN_PORTFOLIO: "portfolio_id",
}

_MAX_EVIDENCE_EXCERPT_LENGTH = 300

#: Stateless, configuration-free (spec G2D2 section 17) - module-level
#: singletons rather than threaded through `NodeDependencies`, exactly
#: like `_bounded_unavailable_response`'s use of `localized_message`.
_RESEARCH_CITATION_VERIFIER = ResearchEvidenceCitationVerifier()
_TEXT_SAFETY_VALIDATOR = SharedTextSafetyValidator()


def _bounded_unavailable_response(message_key: LocalizedMessageKey, language: DetectedLanguage) -> dict[str, Any]:
    return {
        "answer_markdown": localize(message_key, language=language), "citations": [],
        "grounding_status": "INSUFFICIENT_EVIDENCE", "navigation_target": None,
    }


#: Bounded, standard XBRL us-gaap concepts for a COMPANY_OVERVIEW
#: snapshot - a fixed, reviewed list, never learner/model-supplied.
_DEFAULT_COMPANY_OVERVIEW_CONCEPTS = (
    "Assets", "Liabilities", "StockholdersEquity", "Revenues", "NetIncomeLoss",
)

#: Common English sentence-leading/finance-generic capitalized words that
#: must never be mistaken for a company-name candidate.
_COMPANY_CANDIDATE_STOPWORDS = frozenset(
    {
        "what", "who", "when", "where", "why", "how", "is", "are", "was", "were", "the", "a", "an", "i",
        "did", "does", "do", "latest", "current", "today", "yesterday", "recent", "recently",
        # Finance-role/regulatory acronyms that are capitalized but are
        # never themselves a company name.
        "ceo", "cfo", "coo", "cto", "sec", "ipo", "gaap", "cik", "10-k", "10-q",
    }
)
_TICKER_PATTERN = re.compile(r"\$([A-Za-z]{1,5})\b")
_CAPITALIZED_WORD_PATTERN = re.compile(r"\b[A-Z][a-zA-Z]{1,30}\b")


def _extract_company_reference(question: str) -> tuple[str | None, str | None]:
    """Bounded, deterministic (no LLM) extraction of a ticker/company-name
    candidate from free learner text - `request_live_research` never
    invents or guesses a CIK, so the actual resolution (and rejection of
    an ambiguous/unmatched candidate) always happens through
    `CikResolverPort`, never here. Returns `(ticker, company_name)` -
    at most one is set. Deliberately conservative: no candidate is
    returned rather than risk resolving the wrong company."""
    ticker_match = _TICKER_PATTERN.search(question)
    if ticker_match:
        return ticker_match.group(1).upper(), None

    for word in _CAPITALIZED_WORD_PATTERN.findall(question):
        if word.lower() not in _COMPANY_CANDIDATE_STOPWORDS:
            return None, word

    return None, None


_RESEARCH_SYNTHESIS_PROMPT_VERSION = "research-synthesis-v1"
_RESEARCH_SYNTHESIS_SYSTEM_INSTRUCTIONS = (
    "You are FinQuest's research assistant. Answer the learner's question using only the evidence "
    "provided below - never invent a fact, source, or evidence id. Cite every claim by including the "
    "matching evidence id in cited_evidence_ids. If the evidence does not support a confident answer, "
    "say so plainly rather than guessing."
)


async def _grounded_synthesis_response(
    evidence_items: list[Any], *, max_items: int, research_run_id: UUID, user_question: str,
    scope_value: str | None, language: DetectedLanguage, research_model_router: ResearchModelPort | None,
    citation_verifier: ResearchEvidenceCitationVerifier, text_safety_validator: SharedTextSafetyValidator,
) -> dict[str, Any]:
    """Spec G2D2/H1 correction pass, section 6: verified persisted
    `EvidenceItem`s -> bounded research synthesis request -> Ollama/
    OpenAI via `ResearchModelRouter` -> `ResearchEvidenceCitationVerifier`
    -> `SharedTextSafetyValidator` -> bounded final response. The model
    receives only verified `EvidenceItem`s from the owned `ResearchRun`
    (`evidence_items`, already a fresh, run-scoped PostgreSQL read from
    the caller) - no tools, no web search, no file search, no code
    execution, no arbitrary functions. Citations are re-verified against
    `evidence_items` regardless of what the model claims - a fabricated
    or cross-run evidence id is always rejected, never trusted. No
    configured router (SEC/Ollama disabled, or a provider failure) is a
    bounded operational fallback, never a fabricated answer."""
    if research_model_router is None:
        return _bounded_unavailable_response(LocalizedMessageKey.PROVIDER_FAILURE, language)

    bounded_items = evidence_items[:max_items]
    request = ResearchSynthesisRequest(
        system_instructions=_RESEARCH_SYNTHESIS_SYSTEM_INSTRUCTIONS, user_question=user_question,
        scope=ResearchScope(scope_value) if scope_value else ResearchScope.GENERAL_QUESTION,
        evidence_items=[
            ResearchEvidenceInput(
                evidence_id=item.evidence_id, source_title=item.source_title, publisher=item.publisher,
                excerpt=(item.raw_excerpt or item.normalized_text or "")[:_MAX_EVIDENCE_EXCERPT_LENGTH],
                official=item.classification == EvidenceClassification.OFFICIAL,
            )
            for item in bounded_items
        ],
        prompt_version=_RESEARCH_SYNTHESIS_PROMPT_VERSION,
    )

    try:
        result = await research_model_router.generate(request)
    except ResearchModelProviderError:
        return _bounded_unavailable_response(LocalizedMessageKey.PROVIDER_FAILURE, language)

    citation_result = citation_verifier.verify(
        cited_evidence_ids=result.cited_evidence_ids, verified_run_evidence=bounded_items,
        research_run_id=research_run_id,
    )
    if not citation_result.all_verified or not citation_result.verified_evidence_ids:
        return _bounded_unavailable_response(LocalizedMessageKey.PROVIDER_FAILURE, language)

    evidence_by_id = {item.evidence_id: item for item in bounded_items}
    verified_citations: list[dict[str, Any]] = []
    for index, evidence_id in enumerate(
        (eid for eid in result.cited_evidence_ids if eid in citation_result.verified_evidence_ids), start=1
    ):
        item = evidence_by_id.get(evidence_id)
        if item is None:
            continue
        excerpt = (item.raw_excerpt or item.normalized_text or "")[:_MAX_EVIDENCE_EXCERPT_LENGTH]
        verified_citations.append(
            {
                "citation_number": index, "source_title": item.source_title,
                "publisher": item.publisher, "source_url": str(item.source_url) if item.source_url else None,
                "excerpt": excerpt, "official": item.classification == EvidenceClassification.OFFICIAL,
            }
        )

    safety_decision = text_safety_validator.validate(result.answer_markdown)

    return {
        "answer_markdown": safety_decision.bounded_text, "citations": verified_citations,
        "grounding_status": "GROUNDED", "navigation_target": None,
    }


class RunStepLimitExceededError(StockResearchError):
    """The run exceeded its configured `maximum_steps` - a safe, bounded
    failure, never an unbounded loop."""


class InputGuardrailRefusalError(StockResearchError):
    """Not raised in normal flow - used internally to short-circuit to
    `build_refusal_response`'s exact preserved refusal text."""


@dataclass(frozen=True)
class LiveResearchTriggerDependencies:
    """Spec G2D2 section 11: only constructed and passed to
    `NodeDependencies.live_research` when the full flag chain
    (`LANGGRAPH_ENABLED && LANGGRAPH_LIVE_RESEARCH_ROUTE_ENABLED &&
    LIVE_RESEARCH_JOBS_ENABLED && <provider flag>`) is satisfied - every
    other composition passes `None`, and every node below treats `None`
    exactly like `enabled=False`."""

    background_job_service: BackgroundJobService
    account_rate_limiter: AccountResearchRateLimiterPort
    enabled: bool
    max_question_characters: int = 5000
    research_deadline_seconds: int = 600
    #: Spec G2D2/H1 correction pass, section 5: the only authoritative
    #: source of a `sec_cik` for FINANCIAL_FILING_REVIEW/COMPANY_OVERVIEW.
    #: `None` when SEC EDGAR itself is disabled - `request_live_research`
    #: then returns a bounded provider-unavailable response for those two
    #: scopes rather than silently downgrading to NEWS_SCAN.
    cik_resolver: CikResolverPort | None = None


@dataclass(frozen=True)
class NodeDependencies:
    unit_of_work_factory: Callable[[], UnitOfWorkPort]
    intent_classifier: LearningIntentClassifierPort
    context_loader: LearningContextLoaderPort
    action_executor: AllowlistedLearningActionExecutor
    guardrail: RuleBasedTutorGuardrail
    clock: Callable[[], datetime]
    max_context_characters: int = 20_000
    max_state_list_items: int = 50
    # Phase G2E2A: the same shared `LanguageServicePort` instance
    # `GroundedAITutorService` and `LiveResearchRunExecutionJobHandler`
    # are composed with (never a second/third translator implementation).
    # `language_service_enabled=False` (the default) is the kill switch -
    # `evaluate_input_guardrail`/`build_refusal_response`/
    # `build_fallback_response` only ever call `detect_language()` when
    # this is `True`, so a disabled deployment's routing/refusal/fallback
    # text is byte-identical to before this phase.
    language_service: LanguageServicePort = field(default_factory=UnavailableLanguageService)
    language_service_enabled: bool = False
    live_research: LiveResearchTriggerDependencies | None = None
    #: Spec G2D2/H1 correction pass, section 6: `None` when unconfigured
    #: (no Ollama credentials) - `synthesize_research_response` then
    #: takes the bounded provider-unavailable path, never a model call.
    research_model_router: ResearchModelPort | None = None


def stage_label(node_name: str) -> str:
    return _ROUTE_LABELS.get(node_name, node_name.replace("_", " ").title())


def prepared_language_from_state(state: LearningCoachGraphState) -> LanguageQueryPreparation | None:
    """Rebuild this run's single `LanguageQueryPreparation` from state.

    Phase G2E2A req. 3: every route in `subgraphs` that reaches a tutor
    service passes this to `ask(prepared_language=...)`, so the bounded
    English query `evaluate_input_guardrail` already produced is reused
    rather than re-translated - one translation call per run, never one per
    route. Returns `None` when no preparation was recorded (a
    directly-invoked subgraph in a unit test, or a run from before this
    phase's checkpoint schema), in which case the tutor service performs
    its own preparation exactly as it does for a direct `/tutor` request.
    """
    prepared = state.get("language_preparation")
    if not prepared:
        return None
    return LanguageQueryPreparation(
        original_text=state["user_input"],
        detected_language=DetectedLanguage(prepared["detected_language"]),
        search_query=prepared.get("intent_query") or state["user_input"],
        translation_attempted=bool(prepared.get("translation_attempted")),
        translation_failed=bool(prepared.get("translation_failed")),
    )


class GraphNodes:
    """Bound node methods sharing one set of injected dependencies -
    constructed once per worker/API process by `graph_builder.build_graph`,
    exactly like every other FinQuest application service."""

    def __init__(self, deps: NodeDependencies) -> None:
        self._deps = deps

    # -- shared helpers -----------------------------------------------

    async def _append_event(
        self, state: LearningCoachGraphState, *, event_type: LearningOrchestratorEventType, message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        run_id = UUID(state["run_id"])
        async with self._deps.unit_of_work_factory() as uow:
            sequence_number = await uow.learning_orchestrator_events.next_sequence_number(run_id)
            await uow.learning_orchestrator_events.append(
                LearningOrchestratorEvent(
                    run_id=run_id, thread_id=UUID(state["thread_id"]), event_type=event_type,
                    sequence_number=sequence_number, learner_message=message, metadata=metadata or {},
                )
            )
            await uow.commit()

    def _next_step(self, state: LearningCoachGraphState) -> int:
        step_count = state.get("step_count", 0) + 1
        maximum_steps = state.get("maximum_steps", 30)
        if step_count > maximum_steps:
            raise RunStepLimitExceededError(f"Run exceeded its maximum step limit of {maximum_steps}.")
        return step_count

    def _build_tutor_context(self, state: LearningCoachGraphState) -> TutorContext:
        context_type_value = state.get("requested_context_type") or TutorContextType.GENERAL_EDUCATION.value
        references = state.get("context_references", {})
        return TutorContext(
            context_type=TutorContextType(context_type_value), learner_id=UUID(state["learner_id"]),
            lesson_id=UUID(references["lesson_id"]) if "lesson_id" in references else None,
            exercise_id=UUID(references["exercise_id"]) if "exercise_id" in references else None,
            scenario_id=UUID(references["scenario_id"]) if "scenario_id" in references else None,
            scenario_submission_id=(
                UUID(references["scenario_submission_id"]) if "scenario_submission_id" in references else None
            ),
            portfolio_id=UUID(references["portfolio_id"]) if "portfolio_id" in references else None,
        )

    # -- spine nodes -----------------------------------------------

    async def initialize_run(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.RUN_STARTED, message="Run started.",
        )
        return {"step_count": step_count}

    async def load_authorized_context(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        learner_id = UUID(state["learner_id"])
        references = state.get("context_references", {})
        loader = self._deps.context_loader
        result: dict[str, Any] = {"step_count": step_count}

        if "lesson_id" in references:
            result["lesson_metadata"] = await loader.load_lesson_metadata(
                learner_id=learner_id, lesson_id=UUID(references["lesson_id"])
            )
        if "exercise_id" in references:
            result["exercise_metadata"] = await loader.load_exercise_metadata(
                learner_id=learner_id, exercise_id=UUID(references["exercise_id"])
            )
        if "scenario_id" in references:
            submission_id = UUID(references["scenario_submission_id"]) if "scenario_submission_id" in references else None
            result["scenario_metadata"] = await loader.load_scenario_metadata(
                learner_id=learner_id, scenario_id=UUID(references["scenario_id"]), submission_id=submission_id,
            )
        if "portfolio_id" in references:
            result["portfolio_overview"] = await loader.load_portfolio_overview(
                learner_id=learner_id, portfolio_id=UUID(references["portfolio_id"])
            )

        await self._append_event(state, event_type=LearningOrchestratorEventType.CONTEXT_LOADING, message="Context loaded.")
        return result

    def _detect_language(self, user_input: str) -> DetectedLanguage:
        """Phase G2E2A: the single kill switch - `language_service_enabled=False`
        (the default) means this always returns `EN`, so routing/refusal/
        fallback text is byte-identical to before this phase."""
        if not self._deps.language_service_enabled:
            return DetectedLanguage.EN
        return self._deps.language_service.detect_language(user_input)

    @staticmethod
    def _intent_query(state: LearningCoachGraphState) -> str:
        """This run's bounded English query for English-only machinery -
        `state["user_input"]` verbatim whenever no translation happened."""
        prepared = state.get("language_preparation") or {}
        return prepared.get("intent_query") or state["user_input"]

    def _language_from_state(self, state: LearningCoachGraphState) -> DetectedLanguage:
        """The language this run already determined, without repeating any
        work. Falls back to a fresh (pure, free) detection only when the
        node is reached without `evaluate_input_guardrail` having run -
        which never happens in the compiled graph, but keeps each node
        independently callable, as this suite's existing node tests do."""
        prepared = state.get("language_preparation")
        if prepared and prepared.get("detected_language"):
            return DetectedLanguage(prepared["detected_language"])
        return self._detect_language(state.get("user_input", ""))

    async def evaluate_input_guardrail(self, state: LearningCoachGraphState) -> dict[str, Any]:
        """The ONE bounded language-query preparation per Coach request
        (Phase G2E2A req. 3), plus the deterministic guardrail decision.

        `state["user_input"]` is preserved exactly - never overwritten,
        never replaced by a translation. Language is detected from
        `user_input` alone. For Hebrew, exactly one bounded English
        intent/retrieval query is produced here and then reused for
        everything English-only downstream: the translated guardrail
        defense-in-depth pass below, `classify_intent`, and (via
        `subgraphs`) each tutor service's retrieval - so no route causes a
        second translation call for the same run.

        Translation failure fails closed: the run is routed to
        `build_fallback_response` with the exact localized bounded fallback,
        never allowed to continue into intent classification, unrelated
        English retrieval, or model generation with untranslated Hebrew.
        """
        step_count = self._next_step(state)
        context = self._build_tutor_context(state)
        user_input = bounded_text(state["user_input"], max_characters=self._deps.max_context_characters)
        message = TutorMessage(conversation_id=uuid4(), role=TutorMessageRole.USER, content=user_input)

        # Detection is pure and free, so the guardrail runs on the
        # learner's own words FIRST: a request refused there is never
        # translated at all - there is nothing to retrieve for it, and an
        # unsafe question should not be handed to a third-party
        # translation provider just to build a query no one will use.
        detected_language = detect_request_language(
            self._deps.language_service, enabled=self._deps.language_service_enabled, text=user_input,
        )
        decision = self._deps.guardrail.evaluate_input(
            conversation_id=message.conversation_id, message=message, context=context,
            language=detected_language,
            apply_topic_vocabulary_check=detected_language != DetectedLanguage.HE,
            # The feature flag is also the rollout boundary for Hebrew-aware
            # topic vocabulary. With it disabled, retain the pre-G2E2
            # English-only guardrail baseline while keeping every safety
            # rule active against the original input.
            apply_hebrew_topic_vocabulary_check=self._deps.language_service_enabled,
        )
        if decision.action == TutorGuardrailAction.REFUSE:
            return {
                "step_count": step_count,
                "language_preparation": self._language_preparation_state(
                    untranslated_preparation(user_input, detected_language)
                ),
                "guardrail_result": self._guardrail_result_state(decision),
            }

        preparation = await prepare_language_query(
            self._deps.language_service, enabled=self._deps.language_service_enabled,
            text=user_input, detected_language=detected_language,
        )
        language_preparation = self._language_preparation_state(preparation)

        if preparation.translation_failed:
            return {
                "step_count": step_count,
                "language_preparation": language_preparation,
                "guardrail_result": {
                    "action": TutorGuardrailAction.FALLBACK.value,
                    "request_category": TutorRequestCategory.UNSUPPORTED_TOPIC.value,
                    "matched_rule_codes": ["LANGUAGE_TRANSLATION_UNAVAILABLE"],
                    "safe_response_override": self._deps.language_service.localize(
                        LocalizedMessageKey.INSUFFICIENT_EVIDENCE, language=preparation.detected_language
                    ),
                },
            }

        if preparation.translation_succeeded:
            # Defense in depth over the bounded English query - the same
            # deterministic guardrail, and the more restrictive decision
            # always wins. An original-text REFUSE is never downgraded.
            translated_decision = self._deps.guardrail.evaluate_input(
                conversation_id=message.conversation_id,
                message=message.model_copy(update={"content": preparation.search_query}),
                context=context, language=preparation.detected_language,
                apply_topic_vocabulary_check=False,
            )
            decision = more_restrictive_decision(decision, translated_decision)

        return {
            "step_count": step_count, "guardrail_result": self._guardrail_result_state(decision),
            "language_preparation": language_preparation,
        }

    @staticmethod
    def _guardrail_result_state(decision: TutorGuardrailDecision) -> dict[str, Any]:
        return {
            "action": decision.action.value, "request_category": decision.request_category.value,
            "matched_rule_codes": decision.matched_rule_codes,
            "safe_response_override": decision.safe_response_override,
        }

    @staticmethod
    def _language_preparation_state(preparation: LanguageQueryPreparation) -> dict[str, Any]:
        """JSON-serializable only - this goes into the LangGraph
        checkpoint. `intent_query` is the bounded English query, never
        shown to the learner and never persisted as their message."""
        return {
            "detected_language": preparation.detected_language.value,
            "intent_query": preparation.search_query,
            "translation_attempted": preparation.translation_attempted,
            "translation_failed": preparation.translation_failed,
        }

    async def build_refusal_response(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        guardrail_result = state.get("guardrail_result", {})
        detected_language = self._language_from_state(state)
        message = guardrail_result.get("safe_response_override") or self._deps.language_service.localize(
            LocalizedMessageKey.ADVICE_REFUSAL, language=detected_language
        )
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.RUN_COMPLETED, message="Request refused (guardrail).",
        )
        return {
            "step_count": step_count, "selected_route": LearningOrchestratorRoute.REFUSAL.value,
            "final_response": {"answer_markdown": message, "citations": [], "grounding_status": "REFUSED"},
        }

    async def build_fallback_response(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        detected_language = self._language_from_state(state)
        base_message = self._deps.language_service.localize(
            LocalizedMessageKey.INSUFFICIENT_EVIDENCE, language=detected_language
        )
        suggestion = (
            " Ã—Â Ã—Â¡Ã—â€/Ã—â„¢ Ã—Å“Ã—Â©Ã—ÂÃ—â€¢Ã—Å“ Ã—Â¢Ã—Å“ Ã—Å¾Ã—â€¢Ã—Â©Ã—â€™ Ã—Â¤Ã—â„¢Ã—Â Ã—Â Ã—Â¡Ã—â„¢-Ã—â€”Ã—â„¢Ã—Â Ã—â€¢Ã—â€ºÃ—â„¢ Ã—Â¡Ã—Â¤Ã—Â¦Ã—â„¢Ã—Â¤Ã—â„¢, Ã—â€Ã—â€Ã—ÂªÃ—Â§Ã—â€œÃ—Å¾Ã—â€¢Ã—Âª Ã—Â©Ã—Å“Ã—Å¡, Ã—Â©Ã—â„¢Ã—Â¢Ã—â€¢Ã—Â¨, Ã—ÂªÃ—Â¨Ã—â€™Ã—â„¢Ã—Å“, Ã—ÂªÃ—Â¨Ã—â€”Ã—â„¢Ã—Â©, Ã—ÂÃ—â€¢ Ã—ÂªÃ—â„¢Ã—Â§ Ã—â€Ã—â€Ã—Â©Ã—Â§Ã—Â¢Ã—â€¢Ã—Âª Ã—Â©Ã—Å“Ã—Å¡."
            if detected_language == DetectedLanguage.HE
            else (
                " Try asking about a specific financial-education concept, your progress, a lesson, an "
                "exercise, a scenario, or your portfolio."
            )
        )
        message = base_message + suggestion
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.RUN_COMPLETED, message="Request could not be classified.",
        )
        return {
            "step_count": step_count, "selected_route": LearningOrchestratorRoute.FALLBACK.value,
            "final_response": {"answer_markdown": message, "citations": [], "grounding_status": "INSUFFICIENT_EVIDENCE"},
        }

    async def classify_intent(self, state: LearningCoachGraphState) -> dict[str, Any]:
        """Phase G2E2A req. 3: the intent classifier's rule vocabulary (and
        the optional model-assisted fallback's prompt) are English-only, so
        it is given this run's already-prepared bounded English query, not
        the raw Hebrew text - reusing the single translation
        `evaluate_input_guardrail` performed, never issuing a second one.
        For an English request (or a disabled feature flag) the prepared
        query IS `state["user_input"]` verbatim, so English routing is
        byte-identical to before this phase."""
        step_count = self._next_step(state)
        references = {key: UUID(value) for key, value in state.get("context_references", {}).items()}
        classification = await self._deps.intent_classifier.classify(
            learner_id=UUID(state["learner_id"]), user_input=self._intent_query(state),
            context_type=TutorContextType(state.get("requested_context_type") or TutorContextType.GENERAL_EDUCATION.value),
            context_references=references,
        )
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.INTENT_CLASSIFIED,
            message=f"Classified as {classification.intent.value}.",
            metadata={"method": classification.method.value, "confidence": classification.confidence},
        )
        return {
            "step_count": step_count,
            "intent_classification": {
                "intent": classification.intent.value, "confidence": classification.confidence,
                "method": classification.method.value, "matched_rule_codes": classification.matched_rule_codes,
                "requires_grounded_tutor": classification.requires_grounded_tutor,
                "requires_action_approval": classification.requires_action_approval,
                "classifier_version": classification.classifier_version,
            },
        }

    async def select_route(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        intent_value = state.get("intent_classification", {}).get("intent", LearningIntent.UNKNOWN.value)
        scenario_metadata = state.get("scenario_metadata") or {}
        route = pure_select_route(
            intent=LearningIntent(intent_value), scenario_reveal_status=scenario_metadata.get("reveal_status"),
        )
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.ROUTE_SELECTED, message=f"Routed to {route.value}.",
        )
        return {"step_count": step_count, "selected_route": route.value}

    # -- automatic live research (spec G2D2 section 11) -----------------------------------------------

    async def evaluate_current_information(self, state: LearningCoachGraphState) -> dict[str, Any]:
        """Runs only for the `GROUNDED_EXPLANATION` route (see
        `graph_builder._route_after_select_route`) - the deterministic
        current-information decision (spec section 10) never runs for
        practice/diagnostic/progress/scenario/portfolio routes in this
        phase. When the live-research trigger is unconfigured or
        disabled, this is a no-op and the graph proceeds to
        `GROUNDED_EXPLANATION` exactly as before this phase existed."""
        step_count = self._next_step(state)
        live_research = self._deps.live_research
        if live_research is None or not live_research.enabled:
            return {"step_count": step_count}

        decision = classify_information_need(state["user_input"])
        if decision.need != InformationNeed.CURRENT_INFORMATION or decision.scope is None:
            return {"step_count": step_count}
        return {"step_count": step_count, "research_scope": decision.scope.value}

    async def request_live_research(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        language = self._language_from_state(state)
        live_research = self._deps.live_research

        if live_research is None or not live_research.enabled:
            return {
                "step_count": step_count,
                "final_response": _bounded_unavailable_response(LocalizedMessageKey.RESEARCH_UNAVAILABLE, language),
            }

        account_id = UUID(state["trusted_account_id"])
        # The Coach run's own run_id is a stable identity known before
        # any BackgroundJob exists - `release` uses the same id to give
        # back exactly the slot this acquire reserves (spec G2D2/H1
        # correction pass, section 8).
        reservation_id = state["run_id"]
        limit_decision = await live_research.account_rate_limiter.try_acquire(
            account_id=account_id, reservation_id=reservation_id
        )
        if not limit_decision.allowed:
            # Section 18: no job, no ResearchRequest, no internal counter
            # exposed. A rejected request never reserved a slot, so there
            # is nothing to release here.
            return {
                "step_count": step_count,
                "final_response": _bounded_unavailable_response(LocalizedMessageKey.RESEARCH_UNAVAILABLE, language),
            }

        question = bounded_text(state["user_input"], max_characters=live_research.max_question_characters)
        scope = ResearchScope(state.get("research_scope") or ResearchScope.NEWS_SCAN.value)

        raw_parameters: dict[str, Any] = {"original_question": question, "scope": scope.value}
        if scope != ResearchScope.GENERAL_QUESTION:
            raw_parameters["subject_raw_text"] = question[:250]

        # Sections 5/10: FINANCIAL_FILING_REVIEW/COMPANY_OVERVIEW require a
        # `sec_cik` resolved only through the authoritative `CikResolverPort`
        # - never fabricated, never guessed, and never silently downgraded
        # to NEWS_SCAN. Live Research being enabled at all does not imply
        # SEC EDGAR specifically is - `cik_resolver` is `None` whenever
        # SEC EDGAR is disabled, independent of the Perplexity/NEWS_SCAN path.
        if scope in (ResearchScope.FINANCIAL_FILING_REVIEW, ResearchScope.COMPANY_OVERVIEW):
            if live_research.cik_resolver is None:
                # Job-creation rollback (spec G2D2/H1 correction pass,
                # section 8): the concurrency slot was already reserved
                # above, but no job will be created after all - release it.
                await live_research.account_rate_limiter.release(
                    account_id=account_id, reservation_id=reservation_id
                )
                return {
                    "step_count": step_count,
                    "final_response": _bounded_unavailable_response(LocalizedMessageKey.RESEARCH_UNAVAILABLE, language),
                }
            candidate_ticker, candidate_company_name = _extract_company_reference(question)
            if candidate_ticker is None and candidate_company_name is None:
                await live_research.account_rate_limiter.release(
                    account_id=account_id, reservation_id=reservation_id
                )
                return {
                    "step_count": step_count,
                    "final_response": _bounded_unavailable_response(
                        LocalizedMessageKey.CLARIFICATION_NEEDED_COMPANY, language
                    ),
                }
            resolution = await live_research.cik_resolver.resolve(
                ticker=candidate_ticker, company_name=candidate_company_name
            )
            if resolution.status != CikResolutionStatus.RESOLVED or resolution.cik is None:
                await live_research.account_rate_limiter.release(
                    account_id=account_id, reservation_id=reservation_id
                )
                return {
                    "step_count": step_count,
                    "final_response": _bounded_unavailable_response(
                        LocalizedMessageKey.CLARIFICATION_NEEDED_COMPANY, language
                    ),
                }
            raw_parameters["sec_cik"] = resolution.cik
            if scope == ResearchScope.COMPANY_OVERVIEW:
                raw_parameters["sec_concepts"] = list(_DEFAULT_COMPANY_OVERVIEW_CONCEPTS)

        idempotency_key = f"coach-live-research:{state['run_id']}"
        try:
            creation_result = await live_research.background_job_service.create_job(
                job_type=BackgroundJobType.LIVE_RESEARCH_RUN_EXECUTION, raw_parameters=raw_parameters,
                idempotency_key=idempotency_key, trigger_source=JobTriggerSource.SYSTEM,
                requested_by_account_id=account_id,
            )
        except Exception:
            await live_research.account_rate_limiter.release(
                account_id=account_id, reservation_id=reservation_id
            )
            return {
                "step_count": step_count,
                "final_response": _bounded_unavailable_response(LocalizedMessageKey.RESEARCH_UNAVAILABLE, language),
            }
        if creation_result.job.status not in (
            BackgroundJobStatus.PENDING, BackgroundJobStatus.QUEUED, BackgroundJobStatus.RETRY_SCHEDULED
        ):
            await live_research.account_rate_limiter.release(
                account_id=account_id, reservation_id=reservation_id
            )
            return {
                "step_count": step_count,
                "final_response": _bounded_unavailable_response(LocalizedMessageKey.RESEARCH_UNAVAILABLE, language),
            }

        now = self._deps.clock()
        deadline_at = now + timedelta(seconds=live_research.research_deadline_seconds)
        async with self._deps.unit_of_work_factory() as uow:
            await uow.learning_orchestrator_runs.mark_waiting_for_research(
                UUID(state["run_id"]), waiting_at=now, research_job_id=creation_result.job.job_id,
                research_deadline_at=deadline_at,
            )
            await uow.commit()
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.RESEARCH_REQUESTED,
            message="Requested live research.", metadata={"scope": scope.value},
        )

        return {
            "step_count": step_count, "research_job_id": str(creation_result.job.job_id),
            "research_deadline_at": deadline_at.isoformat(),
        }

    async def await_research_result(self, state: LearningCoachGraphState) -> dict[str, Any]:
        """Pauses the run until `COACH_RESEARCH_RESUME` resumes it with
        bounded outcome metadata (spec section 16) - never raw evidence.
        The only other `interrupt()` call site in this graph is
        `approval_interrupt`; this one is driven by the system
        (`COACH_RESEARCH_RESUME`), never directly by a learner action."""
        step_count = self._next_step(state)
        payload = {
            "research_job_id": state.get("research_job_id"), "scope": state.get("research_scope"),
            "deadline_at": state.get("research_deadline_at"),
        }
        resume_value = interrupt(payload)
        return {"step_count": step_count, "research_outcome": resume_value}

    async def synthesize_research_response(self, state: LearningCoachGraphState) -> dict[str, Any]:
        """Spec G2D2/H1 correction pass, section 6: builds a bounded,
        never-fabricated answer from verified `EvidenceItem` rows
        reloaded from PostgreSQL, routed through the grounded synthesis
        order (verified evidence -> `ResearchModelRouter` (Ollama/OpenAI)
        -> `ResearchEvidenceCitationVerifier` -> `SharedTextSafetyValidator`
        -> final output bounding) - the resume payload's outcome metadata
        decides which branch runs, but evidence content itself is never
        trusted from the resume payload, only from a fresh repository
        read."""
        step_count = self._next_step(state)
        language = self._language_from_state(state)
        outcome = state.get("research_outcome") or {}
        outcome_type = outcome.get("outcome")

        if outcome_type == "EVIDENCE_FOUND":
            research_run_id = outcome.get("research_run_id")
            evidence_items = []
            if research_run_id:
                async with self._deps.unit_of_work_factory() as uow:
                    evidence_items = await uow.evidence_items.list_for_run(UUID(research_run_id))
            if evidence_items:
                await self._append_event(
                    state, event_type=LearningOrchestratorEventType.RESEARCH_RESOLVED,
                    message="Live research resolved with evidence.",
                )
                return {
                    "step_count": step_count,
                    "final_response": await _grounded_synthesis_response(
                        evidence_items, max_items=self._deps.max_state_list_items,
                        research_run_id=UUID(research_run_id), user_question=state["user_input"],
                        scope_value=state.get("research_scope"), language=language,
                        research_model_router=self._deps.research_model_router,
                        citation_verifier=_RESEARCH_CITATION_VERIFIER, text_safety_validator=_TEXT_SAFETY_VALIDATOR,
                    ),
                }
            # EVIDENCE_FOUND outcome metadata but nothing loads from
            # PostgreSQL is an inconsistent state - fail closed to the
            # no-evidence message rather than fabricate an answer.
            outcome_type = "NO_EVIDENCE_FOUND"

        await self._append_event(
            state, event_type=LearningOrchestratorEventType.RESEARCH_RESOLVED,
            message=f"Live research resolved: {outcome_type or 'UNKNOWN'}.",
        )
        message_key = {
            "NO_EVIDENCE_FOUND": LocalizedMessageKey.RESEARCH_NO_EVIDENCE,
            "CANCELLED": LocalizedMessageKey.RESEARCH_UNAVAILABLE,
        }.get(outcome_type, LocalizedMessageKey.PROVIDER_FAILURE)
        return {"step_count": step_count, "final_response": _bounded_unavailable_response(message_key, language)}

    # -- action proposal / approval / execution -----------------------------------------------

    async def build_action_proposal(self, state: LearningCoachGraphState) -> dict[str, Any]:
        """Persists the durable `LearningActionProposal` a subgraph
        assembled (action type, title, description, reason, safe
        parameters) into `state["proposed_action"]`. Nothing here has
        executed the action yet - this only records that it was
        *proposed*, per spec ss15's `build_action_proposal -> persist ->
        approval_interrupt` sequence."""
        step_count = self._next_step(state)
        draft = state.get("proposed_action")
        if not draft:
            return {"step_count": step_count, "safe_errors": state.get("safe_errors", []) + ["No action was proposed."]}

        action_type = LearningActionType(draft["action_type"])
        idempotency_key = f"{state['run_id']}:{action_type.value}"
        async with self._deps.unit_of_work_factory() as uow:
            existing = await uow.learning_orchestrator_actions.get_by_idempotency_key(
                run_id=UUID(state["run_id"]), idempotency_key=idempotency_key
            )
            if existing is None:
                proposal = LearningActionProposal(
                    run_id=UUID(state["run_id"]), thread_id=UUID(state["thread_id"]),
                    learner_id=UUID(state["learner_id"]), action_type=action_type, title=draft["title"],
                    description=draft["description"], reason=draft["reason"], parameters=draft.get("parameters", {}),
                    idempotency_key=idempotency_key, expires_at=None,
                )
                existing = await uow.learning_orchestrator_actions.create(proposal)
                await uow.commit()

        await self._append_event(
            state, event_type=LearningOrchestratorEventType.ACTION_PROPOSED,
            message=f"Proposed action: {draft['title']}.",
        )
        return {
            "step_count": step_count,
            "proposed_action": {
                "proposal_id": str(existing.proposal_id), "action_type": action_type.value, "title": existing.title,
                "description": existing.description, "reason": existing.reason,
                "safe_parameters": existing.parameters, "expires_at": None,
            },
        }

    async def approval_interrupt(self, state: LearningCoachGraphState) -> dict[str, Any]:
        """Calls `interrupt()` *before* any mutating side effect - the
        proposal record itself is a durable *proposal*, not yet an
        executed action; nothing in `LearningActionType`'s allow-list has
        run yet when this pauses."""
        step_count = self._next_step(state)
        proposed_action = state.get("proposed_action")
        if not proposed_action:
            return {"step_count": step_count, "safe_errors": state.get("safe_errors", []) + ["No action was proposed."]}

        async with self._deps.unit_of_work_factory() as uow:
            proposal_id = UUID(proposed_action["proposal_id"])
            await uow.learning_orchestrator_actions.mark_waiting_for_approval(proposal_id)
            await uow.commit()
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.APPROVAL_REQUIRED,
            message="Waiting for learner approval.",
        )

        approval_request = {
            "proposal_id": proposed_action["proposal_id"], "title": proposed_action["title"],
            "description": proposed_action["description"], "reason": proposed_action["reason"],
            "safe_parameters": proposed_action.get("safe_parameters", {}), "expires_at": proposed_action.get("expires_at"),
        }
        resume_value = interrupt(approval_request)
        return {"step_count": step_count, "approval_result": resume_value}

    async def execute_action(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        approval_result = state.get("approval_result") or {}
        proposed_action = state.get("proposed_action") or {}
        decision = approval_result.get("decision")

        if decision != "APPROVE" and decision != "EDIT":
            await self._append_event(
                state, event_type=LearningOrchestratorEventType.ACTION_REJECTED, message="Action not approved.",
            )
            return {
                "step_count": step_count,
                "final_response": {
                    "answer_markdown": "No problem - I won't take that action. Let me know if you'd like something else.",
                    "citations": [], "grounding_status": "GROUNDED", "navigation_target": None,
                },
            }

        proposal_id = UUID(proposed_action["proposal_id"])
        async with self._deps.unit_of_work_factory() as uow:
            proposal = await uow.learning_orchestrator_actions.get_by_id(proposal_id)
            if proposal is None:
                raise ForbiddenLearningActionError(f"Proposal '{proposal_id}' no longer exists.")
            now = self._deps.clock()
            executing = await uow.learning_orchestrator_actions.mark_executing(proposal_id, executed_at=now)
            await uow.commit()

        await self._append_event(state, event_type=LearningOrchestratorEventType.ACTION_EXECUTING, message="Executing action.")
        try:
            result = await self._deps.action_executor.execute(learner_id=UUID(state["learner_id"]), proposal=executing)
        except Exception as exc:  # noqa: BLE001 - an action-execution failure must degrade gracefully, never crash the run
            async with self._deps.unit_of_work_factory() as uow:
                await uow.learning_orchestrator_actions.mark_failed(proposal_id, completed_at=self._deps.clock())
                await uow.commit()
            return {
                "step_count": step_count,
                "safe_errors": state.get("safe_errors", []) + [f"The action could not be completed: {type(exc).__name__}."],
                "final_response": {
                    "answer_markdown": "I couldn't complete that action. Please try again from the relevant page.",
                    "citations": [], "grounding_status": "GROUNDED", "navigation_target": None,
                },
            }

        async with self._deps.unit_of_work_factory() as uow:
            await uow.learning_orchestrator_actions.mark_succeeded(
                proposal_id, completed_at=self._deps.clock(), result_reference=result,
            )
            await uow.commit()
        await self._append_event(state, event_type=LearningOrchestratorEventType.ACTION_COMPLETED, message="Action completed.")

        return {
            "step_count": step_count, "action_result": result,
            "navigation_target": result.get("navigation_target"),
            "final_response": {
                "answer_markdown": f"Done - {proposed_action.get('title', 'the action')} is ready.",
                "citations": [], "grounding_status": "GROUNDED", "navigation_target": result.get("navigation_target"),
            },
        }

    # -- output validation and persistence -----------------------------------------------

    async def validate_final_output(self, state: LearningCoachGraphState) -> dict[str, Any]:
        step_count = self._next_step(state)
        final_response = dict(state.get("final_response") or {})
        citations = bounded_list(state.get("citations", []), max_items=self._deps.max_state_list_items)
        final_response.setdefault("citations", citations)
        final_response.setdefault("navigation_target", state.get("navigation_target"))

        for forbidden_key in ("prompt", "chain_of_thought", "reasoning", "raw_state"):
            final_response.pop(forbidden_key, None)

        return {"step_count": step_count, "final_response": final_response}

    async def persist_final_result(self, state: LearningCoachGraphState) -> dict[str, Any]:
        """G2D2/H1 correction pass, section 3: the `RUN_COMPLETED` event's
        `metadata` carries the same bounded `final_response` dict
        (`answer_markdown`/`citations`/`grounding_status`/
        `navigation_target`) the SSE `response_completed`/`research_
        completed`/`research_unavailable` events already expose - this is
        what lets a frontend that reconnected via polling (after the
        original SSE connection closed on a research interrupt) fetch the
        resumed answer through the existing, ownership-checked `GET
        /runs/{run_id}/events` endpoint, with no new backend surface."""
        step_count = self._next_step(state)
        await self._append_event(
            state, event_type=LearningOrchestratorEventType.RUN_COMPLETED, message="Run completed.",
            metadata=state.get("final_response") or {},
        )
        return {"step_count": step_count}

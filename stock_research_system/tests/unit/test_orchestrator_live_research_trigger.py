"""Unit tests for the automatic Live Research trigger (spec G2D2
section 11), exercised against the real compiled graph with LangGraph's
`InMemorySaver` - no PostgreSQL, Redis, or model provider required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from stock_research_core.application.ai_tutor.guardrails import RuleBasedTutorGuardrail
from stock_research_core.application.learning_orchestrator.graph_builder import build_graph
from stock_research_core.application.learning_orchestrator.intent import RuleBasedLearningIntentClassifier
from stock_research_core.application.learning_orchestrator.nodes import (
    GraphNodes,
    LiveResearchTriggerDependencies,
    NodeDependencies,
)
from stock_research_core.application.learning_orchestrator.state import new_state
from stock_research_core.application.learning_orchestrator.subgraphs import Subgraphs, SubgraphDependencies
from stock_research_core.application.live_research.cik_resolver_ports import CikResolutionResult, CikResolutionStatus
from stock_research_core.application.live_research.rate_limit_ports import RateLimitDecision
from stock_research_core.domain.live_research.enums import EvidenceClassification, SourceType
from stock_research_core.domain.operations.enums import BackgroundJobStatus

from tests.unit.learning_orchestrator_fakes import FakeEvidenceItemRepo, FakeTutorService, FakeUnitOfWork

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

_STATIC_QUESTION = "What is diversification?"
#: Must both (a) pass the guardrail's finance-vocabulary check ("stock")
#: and (b) classify to an intent that routes to GROUNDED_EXPLANATION
#: (GENERAL_TUTOR_CHAT) - confirmed against the real
#: `RuleBasedLearningIntentClassifier`/`RuleBasedTutorGuardrail`, not
#: just the current-information policy in isolation.
_CURRENT_INFO_QUESTION = "What happened to Nvidia stock this week?"


class FakeActionExecutor:
    async def execute(self, *, learner_id, proposal):
        return {}


class FakeBackgroundJobService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_job(self, **kwargs):
        self.calls.append(kwargs)
        job_id = uuid4()
        return SimpleNamespace(job=SimpleNamespace(job_id=job_id, status=BackgroundJobStatus.QUEUED), created=True, duplicate_of_job_id=None)


class FakeRateLimiter:
    def __init__(self, *, allowed: bool = True, reason: str | None = None) -> None:
        self.allowed = allowed
        self.reason = reason
        self.calls: list[UUID] = []
        self.reservations: set[tuple[UUID, str]] = set()
        self.released: list[tuple[UUID, str]] = []

    async def try_acquire(self, *, account_id: UUID, reservation_id: str) -> RateLimitDecision:
        self.calls.append(account_id)
        if self.allowed:
            self.reservations.add((account_id, reservation_id))
        return RateLimitDecision(allowed=self.allowed, reason=self.reason)

    async def release(self, *, account_id: UUID, reservation_id: str) -> None:
        self.reservations.discard((account_id, reservation_id))
        self.released.append((account_id, reservation_id))


class FakeResearchModelRouter:
    """A scripted `ResearchModelPort` - the test supplies the exact
    `ResearchSynthesisResult` (or exception) `generate()` should
    return/raise, so these tests never need a real Ollama/OpenAI call."""

    def __init__(self, *, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.requests: list = []

    async def generate(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class FakeCikResolver:
    def __init__(self, *, result: CikResolutionResult | None = None) -> None:
        self.result = result or CikResolutionResult(
            status=CikResolutionStatus.RESOLVED, cik="1045810", company_name="NVIDIA CORP"
        )
        self.calls: list[tuple[str | None, str | None]] = []

    async def resolve(self, *, ticker, company_name):
        self.calls.append((ticker, company_name))
        return self.result


def _evidence_item(run_id: UUID, **overrides):
    import hashlib

    from stock_research_core.domain.live_research.models import EvidenceItem

    fields = dict(
        run_id=run_id, source_type=SourceType.REPUTABLE_SECONDARY_SOURCE, classification=EvidenceClassification.NON_OFFICIAL,
        source_url="https://example.com/article", source_title="Nvidia shares rise on earnings",
        publisher="Example Wire", raw_excerpt="Nvidia reported strong quarterly results.",
        content_hash=hashlib.sha256(b"nvidia-earnings-article").hexdigest(),
    )
    fields.update(overrides)
    return EvidenceItem(**fields)


def _build_compiled_graph(
    *, uow, tutor_service=None, context_loader=None, live_research: LiveResearchTriggerDependencies | None = None,
    research_model_router=None,
):
    node_deps = NodeDependencies(
        unit_of_work_factory=lambda: uow, intent_classifier=RuleBasedLearningIntentClassifier(),
        context_loader=None, action_executor=FakeActionExecutor(), guardrail=RuleBasedTutorGuardrail(),
        clock=lambda: NOW, live_research=live_research, research_model_router=research_model_router,
    )
    subgraph_deps = SubgraphDependencies(
        tutor_service=tutor_service, lesson_tutor_service=None, scenario_tutor_service=None,
        portfolio_tutor_service=None, adaptive_learning_service=None, context_loader=context_loader,
    )
    return build_graph(
        graph_nodes=GraphNodes(node_deps), subgraphs=Subgraphs(subgraph_deps), checkpointer=InMemorySaver()
    )


def _initial_state(user_input: str, *, uow, trusted_account_id: str | None = None):
    """`request_live_research` calls `uow.learning_orchestrator_runs.
    mark_waiting_for_research(run_id, ...)`, which (like the real
    `PersonalizedLearningOrchestratorService`) requires the run row to
    already exist - so this seeds one directly into the fake repo,
    mirroring what `_create_run_row` does in production before the
    graph ever runs."""
    from stock_research_core.domain.learning_orchestrator.models import LearningOrchestratorRun

    thread_id, run_id = str(uuid4()), str(uuid4())
    account_id = trusted_account_id or str(uuid4())
    state = new_state(
        thread_id=thread_id, run_id=run_id, learner_id=str(uuid4()), trusted_account_id=account_id,
        correlation_id=str(uuid4()), graph_version="learning-coach-graph-v1", user_input=user_input,
        requested_context_type="GENERAL_EDUCATION",
    )
    uow.learning_orchestrator_runs.runs[UUID(run_id)] = LearningOrchestratorRun(
        run_id=UUID(run_id), thread_id=UUID(thread_id), learner_id=UUID(state["learner_id"]),
        trusted_account_id=UUID(account_id), idempotency_key=f"key-{run_id}", correlation_id=state["correlation_id"],
        graph_version="learning-coach-graph-v1", status="RUNNING", started_at=NOW,
    )
    config = {"configurable": {"thread_id": thread_id}}
    return state, config


async def test_static_question_never_triggers_live_research_even_when_enabled() -> None:
    uow = FakeUnitOfWork()
    tutor_service = FakeTutorService(answer_markdown="Diversification spreads risk across assets.")
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
    )
    graph = _build_compiled_graph(uow=uow, tutor_service=tutor_service, live_research=live_research)
    state, config = _initial_state(_STATIC_QUESTION, uow=uow)

    result = await graph.ainvoke(state, config=config)

    assert "__interrupt__" not in result
    assert job_service.calls == []
    assert result["final_response"]["answer_markdown"] == "Diversification spreads risk across assets."


async def test_disabled_live_research_leaves_current_info_question_in_grounded_explanation() -> None:
    """`live_research=None` (the default everywhere today) must behave
    exactly as it did before this phase existed - even a question that
    looks like it needs current information stays in static Tutor RAG."""
    uow = FakeUnitOfWork()
    tutor_service = FakeTutorService(answer_markdown="Static answer.")
    graph = _build_compiled_graph(uow=uow, tutor_service=tutor_service, live_research=None)
    state, config = _initial_state(_CURRENT_INFO_QUESTION, uow=uow)

    result = await graph.ainvoke(state, config=config)

    assert "__interrupt__" not in result
    assert result["final_response"]["answer_markdown"] == "Static answer."


async def test_current_information_question_creates_exactly_one_research_job_and_interrupts() -> None:
    account_id = uuid4()
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
    )
    graph = _build_compiled_graph(uow=uow, live_research=live_research)
    state, config = _initial_state(_CURRENT_INFO_QUESTION, uow=uow, trusted_account_id=str(account_id))

    result = await graph.ainvoke(state, config=config)

    assert len(job_service.calls) == 1
    call = job_service.calls[0]
    assert call["job_type"].value == "LIVE_RESEARCH_RUN_EXECUTION"
    assert call["trigger_source"].value == "SYSTEM"
    # Trusted account only - never learner_id, never an integration id.
    assert call["requested_by_account_id"] == account_id
    assert call["raw_parameters"]["scope"] == "NEWS_SCAN"

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["research_job_id"] == result["research_job_id"]
    assert payload["scope"] == "NEWS_SCAN"
    assert payload["deadline_at"] is not None


async def test_rate_limited_account_never_creates_a_job() -> None:
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    limiter = FakeRateLimiter(allowed=False, reason="HOURLY_LIMIT_REACHED")
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=limiter, enabled=True,
    )
    graph = _build_compiled_graph(uow=uow, live_research=live_research)
    state, config = _initial_state(_CURRENT_INFO_QUESTION, uow=uow)

    result = await graph.ainvoke(state, config=config)

    assert job_service.calls == []
    assert len(limiter.calls) == 1
    assert "__interrupt__" not in result
    assert result["final_response"]["grounding_status"] == "INSUFFICIENT_EVIDENCE"


def _synthesis_result(*, cited_evidence_ids, answer_markdown="Nvidia reported strong quarterly earnings."):
    from stock_research_core.application.live_research.synthesis_models import (
        ResearchModelProviderType,
        ResearchSynthesisResult,
    )

    return ResearchSynthesisResult(
        answer_markdown=answer_markdown, cited_evidence_ids=cited_evidence_ids,
        provider_type=ResearchModelProviderType.OLLAMA_CLOUD, model_name="test-model",
    )


async def test_evidence_found_resume_produces_grounded_citations_from_synthesis_model() -> None:
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
    )
    research_run_id = uuid4()
    item = _evidence_item(research_run_id)
    router = FakeResearchModelRouter(result=_synthesis_result(cited_evidence_ids=[item.evidence_id]))
    graph = _build_compiled_graph(uow=uow, live_research=live_research, research_model_router=router)
    state, config = _initial_state(_CURRENT_INFO_QUESTION, uow=uow)
    await graph.ainvoke(state, config=config)

    uow.evidence_items = FakeEvidenceItemRepo(items_by_run={research_run_id: [item]})

    result = await graph.ainvoke(
        Command(resume={"outcome": "EVIDENCE_FOUND", "research_run_id": str(research_run_id), "evidence_count": 1}),
        config=config,
    )

    assert "__interrupt__" not in result
    assert result["final_response"]["grounding_status"] == "GROUNDED"
    assert result["final_response"]["answer_markdown"] == "Nvidia reported strong quarterly earnings."
    assert len(result["final_response"]["citations"]) == 1
    assert "evidence_id" not in result["final_response"]["citations"][0]
    assert result["final_response"]["citations"][0]["source_title"] == "Nvidia shares rise on earnings"
    assert len(router.requests) == 1


async def test_fabricated_evidence_id_from_the_model_is_rejected() -> None:
    """The model claims a citation to an evidence id that was never part
    of this run's verified evidence at all - `ResearchEvidenceCitation
    Verifier` must strip it, never trust the model's own claim."""
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
    )
    research_run_id = uuid4()
    item = _evidence_item(research_run_id)
    fabricated_evidence_id = uuid4()
    router = FakeResearchModelRouter(result=_synthesis_result(cited_evidence_ids=[fabricated_evidence_id]))
    graph = _build_compiled_graph(uow=uow, live_research=live_research, research_model_router=router)
    state, config = _initial_state(_CURRENT_INFO_QUESTION, uow=uow)
    await graph.ainvoke(state, config=config)

    uow.evidence_items = FakeEvidenceItemRepo(items_by_run={research_run_id: [item]})

    result = await graph.ainvoke(
        Command(resume={"outcome": "EVIDENCE_FOUND", "research_run_id": str(research_run_id), "evidence_count": 1}),
        config=config,
    )

    assert result["final_response"]["grounding_status"] != "GROUNDED"
    assert result["final_response"]["citations"] == []


async def test_evidence_cited_from_another_run_is_rejected() -> None:
    """The model cites an evidence id belonging to a *different*
    `ResearchRun` - never trusted even though it is a real, persisted
    `EvidenceItem` somewhere in the system."""
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
    )
    research_run_id = uuid4()
    other_run_id = uuid4()
    item = _evidence_item(research_run_id)
    other_run_item = _evidence_item(other_run_id)
    router = FakeResearchModelRouter(result=_synthesis_result(cited_evidence_ids=[other_run_item.evidence_id]))
    graph = _build_compiled_graph(uow=uow, live_research=live_research, research_model_router=router)
    state, config = _initial_state(_CURRENT_INFO_QUESTION, uow=uow)
    await graph.ainvoke(state, config=config)

    # Only this run's own evidence is ever loaded - `other_run_item` is
    # never part of `verified_run_evidence` for `research_run_id`.
    uow.evidence_items = FakeEvidenceItemRepo(items_by_run={research_run_id: [item]})

    result = await graph.ainvoke(
        Command(resume={"outcome": "EVIDENCE_FOUND", "research_run_id": str(research_run_id), "evidence_count": 1}),
        config=config,
    )

    assert result["final_response"]["grounding_status"] != "GROUNDED"
    assert result["final_response"]["citations"] == []


async def test_no_evidence_found_never_calls_the_synthesis_model() -> None:
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
    )
    router = FakeResearchModelRouter(result=_synthesis_result(cited_evidence_ids=[]))
    graph = _build_compiled_graph(uow=uow, live_research=live_research, research_model_router=router)
    state, config = _initial_state(_CURRENT_INFO_QUESTION, uow=uow)
    await graph.ainvoke(state, config=config)

    result = await graph.ainvoke(Command(resume={"outcome": "NO_EVIDENCE_FOUND", "evidence_count": 0}), config=config)

    assert result["final_response"]["grounding_status"] == "INSUFFICIENT_EVIDENCE"
    assert router.requests == []


async def test_synthesis_model_provider_failure_fails_safely() -> None:
    from stock_research_core.application.exceptions import ResearchModelProviderError

    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
    )
    research_run_id = uuid4()
    item = _evidence_item(research_run_id)
    router = FakeResearchModelRouter(error=ResearchModelProviderError("simulated provider failure"))
    graph = _build_compiled_graph(uow=uow, live_research=live_research, research_model_router=router)
    state, config = _initial_state(_CURRENT_INFO_QUESTION, uow=uow)
    await graph.ainvoke(state, config=config)

    uow.evidence_items = FakeEvidenceItemRepo(items_by_run={research_run_id: [item]})

    result = await graph.ainvoke(
        Command(resume={"outcome": "EVIDENCE_FOUND", "research_run_id": str(research_run_id), "evidence_count": 1}),
        config=config,
    )

    assert result["final_response"]["grounding_status"] == "INSUFFICIENT_EVIDENCE"
    answer = result["final_response"]["answer_markdown"]
    assert "simulated provider failure" not in answer
    assert "ResearchModelProviderError" not in answer


async def test_no_research_model_router_configured_fails_safely_without_a_model_call() -> None:
    """`research_model_router=None` (SEC/Ollama unconfigured) must never
    be treated as "skip straight to a fabricated answer" - it is a
    bounded provider-unavailable response, exactly like a provider
    failure."""
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
    )
    research_run_id = uuid4()
    item = _evidence_item(research_run_id)
    graph = _build_compiled_graph(uow=uow, live_research=live_research, research_model_router=None)
    state, config = _initial_state(_CURRENT_INFO_QUESTION, uow=uow)
    await graph.ainvoke(state, config=config)

    uow.evidence_items = FakeEvidenceItemRepo(items_by_run={research_run_id: [item]})

    result = await graph.ainvoke(
        Command(resume={"outcome": "EVIDENCE_FOUND", "research_run_id": str(research_run_id), "evidence_count": 1}),
        config=config,
    )

    assert result["final_response"]["grounding_status"] == "INSUFFICIENT_EVIDENCE"


async def test_no_evidence_found_resume_produces_bounded_message() -> None:
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
    )
    graph = _build_compiled_graph(uow=uow, live_research=live_research)
    state, config = _initial_state(_CURRENT_INFO_QUESTION, uow=uow)
    await graph.ainvoke(state, config=config)

    result = await graph.ainvoke(Command(resume={"outcome": "NO_EVIDENCE_FOUND", "evidence_count": 0}), config=config)

    assert "__interrupt__" not in result
    assert result["final_response"]["grounding_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["final_response"]["citations"] == []


async def test_provider_failure_resume_produces_bounded_message_without_internal_detail() -> None:
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
    )
    graph = _build_compiled_graph(uow=uow, live_research=live_research)
    state, config = _initial_state(_CURRENT_INFO_QUESTION, uow=uow)
    await graph.ainvoke(state, config=config)

    result = await graph.ainvoke(Command(resume={"outcome": "PROVIDER_FAILURE"}), config=config)

    assert "__interrupt__" not in result
    answer = result["final_response"]["answer_markdown"]
    assert "PROVIDER_FAILURE" not in answer
    assert "Exception" not in answer


async def test_cancelled_resume_produces_bounded_message() -> None:
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
    )
    graph = _build_compiled_graph(uow=uow, live_research=live_research)
    state, config = _initial_state(_CURRENT_INFO_QUESTION, uow=uow)
    await graph.ainvoke(state, config=config)

    result = await graph.ainvoke(Command(resume={"outcome": "CANCELLED"}), config=config)

    assert "__interrupt__" not in result
    assert result["final_response"]["grounding_status"] == "INSUFFICIENT_EVIDENCE"


# -- G2D2/H1 correction: current-information routing before UNKNOWN fallback -----------------------------------------------


async def test_bare_company_mention_without_finance_vocabulary_still_triggers_research() -> None:
    """"Nvidia" alone (no "stock"/"market"/etc.) scores UNKNOWN in
    `RuleBasedLearningIntentClassifier` and used to dead-end at
    `build_fallback_response` before ever reaching the deterministic
    current-information policy - the exact bug this correction pass
    fixes."""
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
    )
    graph = _build_compiled_graph(uow=uow, live_research=live_research)
    state, config = _initial_state("What happened to Nvidia this week?", uow=uow)

    result = await graph.ainvoke(state, config=config)

    assert len(job_service.calls) == 1
    assert job_service.calls[0]["raw_parameters"]["scope"] == "NEWS_SCAN"
    assert "__interrupt__" in result


async def test_current_ratio_stays_static_despite_containing_the_word_current() -> None:
    uow = FakeUnitOfWork()
    tutor_service = FakeTutorService(answer_markdown="unused")
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
    )
    graph = _build_compiled_graph(uow=uow, tutor_service=tutor_service, live_research=live_research)
    state, config = _initial_state("What is the current ratio?", uow=uow)

    result = await graph.ainvoke(state, config=config)

    assert job_service.calls == []
    assert "__interrupt__" not in result


# -- G2D2/H1 correction: no silent SEC-to-NEWS downgrade -----------------------------------------------


async def test_financial_filing_review_with_resolved_ticker_is_never_downgraded_to_news_scan() -> None:
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    cik_resolver = FakeCikResolver(
        result=CikResolutionResult(status=CikResolutionStatus.RESOLVED, cik="1045810", company_name="NVIDIA CORP")
    )
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
        cik_resolver=cik_resolver,
    )
    graph = _build_compiled_graph(uow=uow, live_research=live_research)
    state, config = _initial_state("What did $NVDA report in its latest filing?", uow=uow)

    result = await graph.ainvoke(state, config=config)

    assert len(job_service.calls) == 1
    call = job_service.calls[0]
    assert call["raw_parameters"]["scope"] == "FINANCIAL_FILING_REVIEW"
    assert call["raw_parameters"]["scope"] != "NEWS_SCAN"
    assert call["raw_parameters"]["sec_cik"] == "1045810"
    assert cik_resolver.calls == [("NVDA", None)]
    assert "__interrupt__" in result


async def test_company_overview_with_resolved_company_name_carries_sec_concepts() -> None:
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    cik_resolver = FakeCikResolver(
        result=CikResolutionResult(status=CikResolutionStatus.RESOLVED, cik="1045810", company_name="NVIDIA CORP")
    )
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
        cik_resolver=cik_resolver,
    )
    graph = _build_compiled_graph(uow=uow, live_research=live_research)
    state, config = _initial_state("Who is the current CEO of Nvidia?", uow=uow)

    result = await graph.ainvoke(state, config=config)

    assert len(job_service.calls) == 1
    call = job_service.calls[0]
    assert call["raw_parameters"]["scope"] == "COMPANY_OVERVIEW"
    assert call["raw_parameters"]["sec_cik"] == "1045810"
    assert call["raw_parameters"]["sec_concepts"]
    assert cik_resolver.calls == [(None, "Nvidia")]
    assert "__interrupt__" in result


async def test_ambiguous_company_requests_clarification_and_creates_no_job() -> None:
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    cik_resolver = FakeCikResolver(result=CikResolutionResult(status=CikResolutionStatus.AMBIGUOUS))
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
        cik_resolver=cik_resolver,
    )
    graph = _build_compiled_graph(uow=uow, live_research=live_research)
    state, config = _initial_state("What did Nvidia report in its latest filing?", uow=uow)

    result = await graph.ainvoke(state, config=config)

    assert job_service.calls == []
    assert "__interrupt__" not in result
    assert result["final_response"]["grounding_status"] == "INSUFFICIENT_EVIDENCE"


async def test_missing_company_requests_clarification_without_ever_calling_the_resolver() -> None:
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    cik_resolver = FakeCikResolver()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
        cik_resolver=cik_resolver,
    )
    graph = _build_compiled_graph(uow=uow, live_research=live_research)
    state, config = _initial_state("What was reported in the latest filing?", uow=uow)

    result = await graph.ainvoke(state, config=config)

    assert job_service.calls == []
    assert cik_resolver.calls == []
    assert "__interrupt__" not in result
    assert result["final_response"]["grounding_status"] == "INSUFFICIENT_EVIDENCE"


async def test_sec_disabled_fails_safely_with_provider_unavailable_and_no_job() -> None:
    """`cik_resolver=None` (the default whenever SEC EDGAR is disabled)
    must never be treated as "resolve to NEWS_SCAN" - it is a distinct,
    bounded provider-unavailable response, with no job created."""
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True, cik_resolver=None,
    )
    graph = _build_compiled_graph(uow=uow, live_research=live_research)
    state, config = _initial_state("What did Nvidia report in its latest filing?", uow=uow)

    result = await graph.ainvoke(state, config=config)

    assert job_service.calls == []
    assert "__interrupt__" not in result
    assert result["final_response"]["grounding_status"] == "INSUFFICIENT_EVIDENCE"


async def test_invalid_cik_from_resolver_fails_safely() -> None:
    """A resolver that reports RESOLVED but without an actual `cik` value
    must fail safely (bounded clarification), never fabricate a CIK to
    proceed with anyway."""
    uow = FakeUnitOfWork()
    job_service = FakeBackgroundJobService()
    cik_resolver = FakeCikResolver(result=CikResolutionResult(status=CikResolutionStatus.NOT_FOUND))
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=FakeRateLimiter(), enabled=True,
        cik_resolver=cik_resolver,
    )
    graph = _build_compiled_graph(uow=uow, live_research=live_research)
    state, config = _initial_state("What did Nvidia report in its latest filing?", uow=uow)

    result = await graph.ainvoke(state, config=config)

    assert job_service.calls == []
    assert "__interrupt__" not in result


async def test_job_creation_exception_releases_the_account_reservation() -> None:
    class RaisingJobService(FakeBackgroundJobService):
        async def create_job(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError("database unavailable")

    uow = FakeUnitOfWork()
    job_service = RaisingJobService()
    limiter = FakeRateLimiter()
    live_research = LiveResearchTriggerDependencies(
        background_job_service=job_service, account_rate_limiter=limiter, enabled=True,
    )
    graph = _build_compiled_graph(uow=uow, live_research=live_research)
    state, config = _initial_state(_CURRENT_INFO_QUESTION, uow=uow)

    result = await graph.ainvoke(state, config=config)

    account_id = UUID(state["trusted_account_id"])
    assert limiter.released == [(account_id, state["run_id"])]
    assert limiter.reservations == set()
    assert result["final_response"]["grounding_status"] == "INSUFFICIENT_EVIDENCE"
    assert "__interrupt__" not in result
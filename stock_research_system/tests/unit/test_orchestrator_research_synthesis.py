"""Unit tests for `application.learning_orchestrator.nodes._grounded_
synthesis_response` - the synthesis-order wiring (spec G2D2/H1
correction pass, section 6: verified evidence -> `ResearchModelRouter`
-> `ResearchEvidenceCitationVerifier` -> `SharedTextSafetyValidator` ->
bounded output) directly, independent of the full graph."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from stock_research_core.application.language.detection import Language
from stock_research_core.application.learning_orchestrator.nodes import _grounded_synthesis_response
from stock_research_core.application.live_research.citation_verifier import ResearchEvidenceCitationVerifier
from stock_research_core.application.live_research.synthesis_models import (
    ResearchModelProviderType,
    ResearchSynthesisResult,
)
from stock_research_core.application.shared.text_safety import SharedTextSafetyValidator
from stock_research_core.domain.live_research.enums import EvidenceClassification, SourceType
from stock_research_core.domain.live_research.models import EvidenceItem


class _FakeRouter:
    def __init__(self, *, result: ResearchSynthesisResult) -> None:
        self.result = result
        self.requests: list = []

    async def generate(self, request):
        self.requests.append(request)
        return self.result


def _evidence(run_id, **overrides) -> EvidenceItem:
    fields = dict(
        run_id=run_id, source_type=SourceType.REPUTABLE_SECONDARY_SOURCE, classification=EvidenceClassification.NON_OFFICIAL,
        source_url="https://example.com/a", source_title="Nvidia earnings beat", publisher="Example Wire",
        raw_excerpt="Nvidia beat estimates.", content_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
    )
    fields.update(overrides)
    return EvidenceItem(**fields)


def _result(cited_evidence_ids, answer_markdown="Nvidia beat estimates.") -> ResearchSynthesisResult:
    return ResearchSynthesisResult(
        answer_markdown=answer_markdown, cited_evidence_ids=cited_evidence_ids,
        provider_type=ResearchModelProviderType.OLLAMA_CLOUD, model_name="test-model",
    )


async def test_a_citation_the_model_returns_from_the_correct_run_is_kept() -> None:
    run_id = uuid4()
    item = _evidence(run_id)
    router = _FakeRouter(result=_result([item.evidence_id]))

    response = await _grounded_synthesis_response(
        [item], max_items=10, research_run_id=run_id, user_question="What happened to Nvidia?", scope_value=None,
        language=Language.ENGLISH, research_model_router=router, citation_verifier=ResearchEvidenceCitationVerifier(),
        text_safety_validator=SharedTextSafetyValidator(),
    )

    assert response["grounding_status"] == "GROUNDED"
    assert len(response["citations"]) == 1
    assert response["citations"][0]["source_title"] == "Nvidia earnings beat"
    assert "Nvidia beat estimates." in response["answer_markdown"]
    assert len(router.requests) == 1


async def test_evidence_from_a_different_run_is_never_cited() -> None:
    """Defense in depth: even if the model cites an evidence id belonging
    to a different run (or a fabricated one), it must never appear in
    the final citations - `evidence_items` passed in is already scoped
    to `research_run_id`, so an id the model claims that is not among
    them is always rejected."""
    correct_run_id, other_run_id = uuid4(), uuid4()
    correct_run_item = _evidence(correct_run_id)
    cross_run_item = _evidence(other_run_id)
    router = _FakeRouter(result=_result([cross_run_item.evidence_id]))

    response = await _grounded_synthesis_response(
        [correct_run_item], max_items=10, research_run_id=correct_run_id, user_question="q", scope_value=None,
        language=Language.ENGLISH, research_model_router=router, citation_verifier=ResearchEvidenceCitationVerifier(),
        text_safety_validator=SharedTextSafetyValidator(),
    )
    assert response["citations"] == []


async def test_official_flag_is_present_on_each_citation() -> None:
    run_id = uuid4()
    official_item = _evidence(run_id, classification=EvidenceClassification.OFFICIAL, source_title="SEC filing")
    router = _FakeRouter(result=_result([official_item.evidence_id]))

    response = await _grounded_synthesis_response(
        [official_item], max_items=10, research_run_id=run_id, user_question="q", scope_value=None,
        language=Language.ENGLISH, research_model_router=router, citation_verifier=ResearchEvidenceCitationVerifier(),
        text_safety_validator=SharedTextSafetyValidator(),
    )
    assert response["citations"][0]["official"] is True


async def test_unsafe_markup_in_the_models_answer_is_stripped() -> None:
    run_id = uuid4()
    item = _evidence(run_id)
    router = _FakeRouter(
        result=_result([item.evidence_id], answer_markdown="Nvidia beat estimates. <script>alert('x')</script>")
    )

    response = await _grounded_synthesis_response(
        [item], max_items=10, research_run_id=run_id, user_question="q", scope_value=None,
        language=Language.ENGLISH, research_model_router=router, citation_verifier=ResearchEvidenceCitationVerifier(),
        text_safety_validator=SharedTextSafetyValidator(),
    )
    assert "<script" not in response["answer_markdown"].lower()


async def test_bounded_max_items_limits_how_much_evidence_reaches_the_model() -> None:
    run_id = uuid4()
    items = [_evidence(run_id) for _ in range(5)]
    router = _FakeRouter(result=_result([item.evidence_id for item in items[:2]]))

    await _grounded_synthesis_response(
        items, max_items=2, research_run_id=run_id, user_question="q", scope_value=None, language=Language.ENGLISH,
        research_model_router=router, citation_verifier=ResearchEvidenceCitationVerifier(),
        text_safety_validator=SharedTextSafetyValidator(),
    )
    assert len(router.requests[0].evidence_items) == 2


async def test_no_router_configured_returns_a_bounded_fallback_without_a_model_call() -> None:
    run_id = uuid4()
    item = _evidence(run_id)

    response = await _grounded_synthesis_response(
        [item], max_items=10, research_run_id=run_id, user_question="q", scope_value=None, language=Language.ENGLISH,
        research_model_router=None, citation_verifier=ResearchEvidenceCitationVerifier(),
        text_safety_validator=SharedTextSafetyValidator(),
    )
    assert response["grounding_status"] == "INSUFFICIENT_EVIDENCE"


async def test_fabricated_citation_fails_closed() -> None:
    run_id = uuid4()
    item = _evidence(run_id)
    response = await _grounded_synthesis_response(
        [item], max_items=10, research_run_id=run_id, user_question="q", scope_value=None,
        language=Language.ENGLISH, research_model_router=_FakeRouter(result=_result([uuid4()])),
        citation_verifier=ResearchEvidenceCitationVerifier(), text_safety_validator=SharedTextSafetyValidator(),
    )
    assert response["grounding_status"] != "GROUNDED"
    assert response["citations"] == []


async def test_mixed_valid_and_fabricated_citations_fail_closed() -> None:
    run_id = uuid4()
    item = _evidence(run_id)
    response = await _grounded_synthesis_response(
        [item], max_items=10, research_run_id=run_id, user_question="q", scope_value=None,
        language=Language.ENGLISH, research_model_router=_FakeRouter(result=_result([item.evidence_id, uuid4()])),
        citation_verifier=ResearchEvidenceCitationVerifier(), text_safety_validator=SharedTextSafetyValidator(),
    )
    assert response["grounding_status"] != "GROUNDED"
    assert response["citations"] == []


async def test_factual_answer_with_no_citations_fails_closed() -> None:
    run_id = uuid4()
    response = await _grounded_synthesis_response(
        [_evidence(run_id)], max_items=10, research_run_id=run_id, user_question="q", scope_value=None,
        language=Language.ENGLISH, research_model_router=_FakeRouter(result=_result([])),
        citation_verifier=ResearchEvidenceCitationVerifier(), text_safety_validator=SharedTextSafetyValidator(),
    )
    assert response["grounding_status"] != "GROUNDED"
    assert response["citations"] == []


async def test_citation_outside_bounded_model_evidence_fails_closed() -> None:
    run_id = uuid4()
    first, outside_bound = _evidence(run_id), _evidence(run_id)
    router = _FakeRouter(result=_result([outside_bound.evidence_id]))
    response = await _grounded_synthesis_response(
        [first, outside_bound], max_items=1, research_run_id=run_id, user_question="q", scope_value=None,
        language=Language.ENGLISH, research_model_router=router,
        citation_verifier=ResearchEvidenceCitationVerifier(), text_safety_validator=SharedTextSafetyValidator(),
    )
    assert len(router.requests[0].evidence_items) == 1
    assert response["grounding_status"] != "GROUNDED"
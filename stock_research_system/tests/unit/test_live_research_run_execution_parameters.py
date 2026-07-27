"""Unit tests for `LiveResearchRunExecutionParameters` (Phase G2B).

Confirms: no requester/idempotency fields exist on the model at all
(correction #2's regression guard); subject/scope validation;
`MARKET_DATA_SNAPSHOT` rejection; SEC CIK normalization/rejection and
concept stripping/deduplication via the canonical G2A1 request models
(never a second, weaker, duplicated validator); irrelevant SEC fields
rejected for discovery-only scopes; and the two independent
question-length boundaries - the normalized `ResearchRequest.
normalized_query` bound that applies to *every* scope, and the
transmitted `DiscoverySearchRequest.query` bound that applies only to
scopes calling discovery search - together with the exact whitespace
normalization those boundaries are measured on.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from stock_research_core.application.operations.models import (
    _NORMALIZED_QUERY_MAX_LENGTH,
    LiveResearchRunExecutionParameters,
)
from stock_research_core.domain.live_research.enums import ResearchScope
from stock_research_core.domain.live_research.hashing import normalize_query
from stock_research_core.domain.live_research.models import ResearchRequest


def _params(**overrides):
    fields = dict(original_question="What is a bond?", scope=ResearchScope.GENERAL_QUESTION)
    fields.update(overrides)
    return LiveResearchRunExecutionParameters(**fields)


class TestNoTrustedIdentityFields:
    """Regression guard for correction #2: these must never be
    declared on the job-parameters model, since `parameters` is the
    untrusted, caller-supplied part of a job-creation request."""

    def test_model_has_no_requester_or_idempotency_fields(self) -> None:
        field_names = set(LiveResearchRunExecutionParameters.model_fields)
        for forbidden in (
            "requested_by_account_id", "requested_by_integration_id",
            "research_idempotency_key", "idempotency_key", "account_id", "integration_id",
        ):
            assert forbidden not in field_names

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LiveResearchRunExecutionParameters(
                original_question="What is a bond?", scope=ResearchScope.GENERAL_QUESTION,
                requested_by_account_id="00000000-0000-0000-0000-000000000000",
            )


class TestSubjectValidation:
    def test_general_question_needs_no_subject(self) -> None:
        params = _params(scope=ResearchScope.GENERAL_QUESTION)
        assert params.subject_security_id is None
        assert params.subject_raw_text is None

    def test_general_question_rejects_subject_security_id(self) -> None:
        # G2B Correction V4, item 1: GENERAL_QUESTION is the one accepted
        # scope with no subject concept at all - a caller-supplied
        # subject_security_id must be rejected outright, not silently
        # accepted/ignored.
        with pytest.raises(ValidationError, match="subject_security_id must not be set"):
            _params(
                scope=ResearchScope.GENERAL_QUESTION,
                subject_security_id="00000000-0000-0000-0000-000000000000",
            )

    def test_general_question_rejects_non_empty_subject_raw_text(self) -> None:
        with pytest.raises(ValidationError, match="subject_raw_text must not be set"):
            _params(scope=ResearchScope.GENERAL_QUESTION, subject_raw_text="Acme Corp")

    def test_non_general_question_requires_a_subject(self) -> None:
        with pytest.raises(ValidationError, match="subject"):
            _params(scope=ResearchScope.NEWS_SCAN)

    def test_non_general_scope_rejects_whitespace_only_subject_raw_text(self) -> None:
        # G2B Correction V4, item 2: a whitespace-only subject_raw_text is
        # normalized to None before `_validate_subject` runs, so it must
        # be treated exactly like "no subject at all" for a scope that
        # requires one - never accepted as a (blank) subject.
        with pytest.raises(ValidationError, match="subject"):
            _params(scope=ResearchScope.NEWS_SCAN, subject_raw_text="   ")

    def test_both_subject_fields_set_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="both"):
            _params(
                scope=ResearchScope.NEWS_SCAN,
                subject_security_id="00000000-0000-0000-0000-000000000000",
                subject_raw_text="Acme Corp",
            )

    def test_subject_raw_text_is_stripped(self) -> None:
        params = _params(scope=ResearchScope.NEWS_SCAN, subject_raw_text="  Acme Corp  ")
        assert params.subject_raw_text == "Acme Corp"

    def test_whitespace_only_subject_raw_text_is_normalized_to_none(self) -> None:
        # Asserted directly against a scope where a bare `None` subject
        # is otherwise valid (GENERAL_QUESTION), isolating the
        # normalization itself from the "subject required" check above.
        params = _params(scope=ResearchScope.GENERAL_QUESTION, subject_raw_text="   ")
        assert params.subject_raw_text is None

    def test_original_question_is_stripped(self) -> None:
        params = _params(original_question="  What is a bond?  ")
        assert params.original_question == "What is a bond?"

    @pytest.mark.parametrize(
        "scope",
        [
            ResearchScope.NEWS_SCAN,
            ResearchScope.ANALYST_SENTIMENT,
            ResearchScope.COMPANY_OVERVIEW,
            ResearchScope.FINANCIAL_FILING_REVIEW,
        ],
    )
    def test_every_non_general_accepted_scope_accepts_exactly_one_subject_via_security_id(
        self, scope: ResearchScope
    ) -> None:
        kwargs: dict = {"scope": scope, "subject_security_id": "00000000-0000-0000-0000-000000000000"}
        if scope in (ResearchScope.COMPANY_OVERVIEW, ResearchScope.FINANCIAL_FILING_REVIEW):
            kwargs["sec_cik"] = "320193"
        if scope == ResearchScope.COMPANY_OVERVIEW:
            kwargs["sec_concepts"] = ["Assets"]
        params = _params(**kwargs)
        assert params.subject_security_id is not None
        assert params.subject_raw_text is None

    @pytest.mark.parametrize(
        "scope",
        [
            ResearchScope.NEWS_SCAN,
            ResearchScope.ANALYST_SENTIMENT,
            ResearchScope.COMPANY_OVERVIEW,
            ResearchScope.FINANCIAL_FILING_REVIEW,
        ],
    )
    def test_every_non_general_accepted_scope_accepts_exactly_one_subject_via_raw_text(
        self, scope: ResearchScope
    ) -> None:
        kwargs: dict = {"scope": scope, "subject_raw_text": "Acme Corp"}
        if scope in (ResearchScope.COMPANY_OVERVIEW, ResearchScope.FINANCIAL_FILING_REVIEW):
            kwargs["sec_cik"] = "320193"
        if scope == ResearchScope.COMPANY_OVERVIEW:
            kwargs["sec_concepts"] = ["Assets"]
        params = _params(**kwargs)
        assert params.subject_raw_text == "Acme Corp"
        assert params.subject_security_id is None


class TestOriginalQuestionValidation:
    def test_whitespace_only_original_question_is_rejected(self) -> None:
        # `DomainModel.model_config` sets `str_strip_whitespace=True`, so
        # Pydantic strips the raw value *before* checking
        # `Field(min_length=3, ...)` - a whitespace-only question
        # therefore strips down to "" and fails that length constraint.
        # Proven here for a scope (FINANCIAL_FILING_REVIEW) that never
        # constructs a `DiscoverySearchRequest`, so no *other* validator
        # in this model could incidentally be the one catching it.
        with pytest.raises(ValidationError, match="at least 3 characters"):
            _filing_params(original_question="   ")

    @pytest.mark.parametrize(
        "scope",
        [
            ResearchScope.GENERAL_QUESTION,
            ResearchScope.NEWS_SCAN,
            ResearchScope.ANALYST_SENTIMENT,
            ResearchScope.COMPANY_OVERVIEW,
            ResearchScope.FINANCIAL_FILING_REVIEW,
        ],
    )
    def test_whitespace_only_original_question_is_rejected_for_every_accepted_scope(
        self, scope: ResearchScope
    ) -> None:
        kwargs: dict = {"original_question": "   ", "scope": scope}
        if scope != ResearchScope.GENERAL_QUESTION:
            kwargs["subject_raw_text"] = "Acme Corp"
        if scope in (ResearchScope.COMPANY_OVERVIEW, ResearchScope.FINANCIAL_FILING_REVIEW):
            kwargs["sec_cik"] = "320193"
        if scope == ResearchScope.COMPANY_OVERVIEW:
            kwargs["sec_concepts"] = ["Assets"]
        with pytest.raises(ValidationError, match="at least 3 characters"):
            LiveResearchRunExecutionParameters(**kwargs)


class TestMarketDataSnapshotRejected:
    def test_market_data_snapshot_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="MARKET_DATA_SNAPSHOT"):
            _params(scope=ResearchScope.MARKET_DATA_SNAPSHOT, subject_raw_text="Acme Corp")


class TestFinancialFilingReview:
    def test_sec_cik_is_required(self) -> None:
        with pytest.raises(ValidationError, match="sec_cik is required"):
            _params(scope=ResearchScope.FINANCIAL_FILING_REVIEW, subject_raw_text="Acme Corp")

    def test_sec_concepts_must_be_absent(self) -> None:
        with pytest.raises(ValidationError, match="sec_concepts must not be set"):
            _params(
                scope=ResearchScope.FINANCIAL_FILING_REVIEW, subject_raw_text="Acme Corp",
                sec_cik="320193", sec_concepts=["Assets"],
            )

    def test_cik_is_normalized_via_the_canonical_g2a1_model(self) -> None:
        params = _params(scope=ResearchScope.FINANCIAL_FILING_REVIEW, subject_raw_text="Acme Corp", sec_cik="320193")
        assert params.sec_cik == "0000320193"

    def test_all_zero_cik_is_rejected_through_canonical_g2a1_model_validation(self) -> None:
        with pytest.raises(ValidationError):
            _params(scope=ResearchScope.FINANCIAL_FILING_REVIEW, subject_raw_text="Acme Corp", sec_cik="0000000000")

    def test_non_numeric_cik_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _params(scope=ResearchScope.FINANCIAL_FILING_REVIEW, subject_raw_text="Acme Corp", sec_cik="not-a-cik")

    def test_oversized_cik_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _params(scope=ResearchScope.FINANCIAL_FILING_REVIEW, subject_raw_text="Acme Corp", sec_cik="12345678901")


class TestCompanyOverview:
    def test_sec_cik_and_sec_concepts_are_both_required(self) -> None:
        with pytest.raises(ValidationError, match="sec_cik is required"):
            _params(scope=ResearchScope.COMPANY_OVERVIEW, subject_raw_text="Acme Corp")

    def test_sec_concepts_required_non_empty(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _params(scope=ResearchScope.COMPANY_OVERVIEW, subject_raw_text="Acme Corp", sec_cik="320193", sec_concepts=[])

    def test_concepts_are_stripped_and_deduplicated_via_canonical_model(self) -> None:
        params = _params(
            scope=ResearchScope.COMPANY_OVERVIEW, subject_raw_text="Acme Corp", sec_cik="320193",
            sec_concepts=["  Assets ", "Assets", "Liabilities"],
        )
        assert params.sec_concepts == ["Assets", "Liabilities"]

    def test_blank_concept_entries_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _params(
                scope=ResearchScope.COMPANY_OVERVIEW, subject_raw_text="Acme Corp", sec_cik="320193",
                sec_concepts=["Assets", "   "],
            )

    def test_oversized_concept_entries_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _params(
                scope=ResearchScope.COMPANY_OVERVIEW, subject_raw_text="Acme Corp", sec_cik="320193",
                sec_concepts=["x" * 201],
            )

    def test_too_many_distinct_concepts_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _params(
                scope=ResearchScope.COMPANY_OVERVIEW, subject_raw_text="Acme Corp", sec_cik="320193",
                sec_concepts=[f"concept-{i}" for i in range(51)],
            )

    def test_cik_is_normalized_alongside_concepts(self) -> None:
        params = _params(
            scope=ResearchScope.COMPANY_OVERVIEW, subject_raw_text="Acme Corp", sec_cik="320193",
            sec_concepts=["Assets"],
        )
        assert params.sec_cik == "0000320193"


class TestDiscoveryOnlyScopesRejectSecFields:
    @pytest.mark.parametrize(
        "scope", [ResearchScope.NEWS_SCAN, ResearchScope.ANALYST_SENTIMENT, ResearchScope.GENERAL_QUESTION]
    )
    def test_sec_cik_is_rejected(self, scope: ResearchScope) -> None:
        kwargs = {} if scope == ResearchScope.GENERAL_QUESTION else {"subject_raw_text": "Acme Corp"}
        with pytest.raises(ValidationError, match="must not be set"):
            _params(scope=scope, sec_cik="320193", **kwargs)

    @pytest.mark.parametrize(
        "scope", [ResearchScope.NEWS_SCAN, ResearchScope.ANALYST_SENTIMENT, ResearchScope.GENERAL_QUESTION]
    )
    def test_sec_concepts_is_rejected(self, scope: ResearchScope) -> None:
        kwargs = {} if scope == ResearchScope.GENERAL_QUESTION else {"subject_raw_text": "Acme Corp"}
        with pytest.raises(ValidationError, match="must not be set"):
            _params(scope=scope, sec_concepts=["Assets"], **kwargs)


def _filing_params(**overrides):
    fields = dict(scope=ResearchScope.FINANCIAL_FILING_REVIEW, subject_raw_text="Acme Corp", sec_cik="320193")
    fields.update(overrides)
    return _params(**fields)


#: A question whose *transmitted* form is 2001 characters but whose
#: *normalized* form is exactly 2000: the single two-space run collapses
#: to one space. The two boundaries in play (transmitted discovery query
#: vs. persisted `ResearchRequest.normalized_query`) are therefore
#: genuinely independent, and this string sits on the far side of one and
#: exactly on the other.
_TRANSMITTED_2001_NORMALIZED_2000 = "x" * 1998 + "  " + "y"


class TestNormalizedQueryBoundary:
    """G2B Correction V3, item 4: `ResearchRequest.normalized_query` is
    `Field(min_length=1, max_length=2000)`, and *every*
    `LIVE_RESEARCH_RUN_EXECUTION` job eventually persists one - so no
    scope is exempt from that boundary, including FINANCIAL_FILING_REVIEW
    (which the previous revision wrongly treated as exempt because it
    never calls discovery search). Enforced during job-parameter
    validation, i.e. before enqueue."""

    def test_the_bound_is_read_from_the_research_request_model_itself(self) -> None:
        # Never a second hard-coded copy of 2000 that could drift.
        assert _NORMALIZED_QUERY_MAX_LENGTH == 2000
        assert any(
            getattr(constraint, "max_length", None) == _NORMALIZED_QUERY_MAX_LENGTH
            for constraint in ResearchRequest.model_fields["normalized_query"].metadata
        )

    def test_filing_normalized_query_of_2001_characters_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="normalized research question exceeds"):
            _filing_params(original_question="x" * 2001)

    def test_filing_normalized_query_of_2000_characters_is_accepted(self) -> None:
        params = _filing_params(original_question="x" * 2000)
        assert len(normalize_query(params.original_question)) == 2000

    @pytest.mark.parametrize(
        "scope",
        [
            ResearchScope.NEWS_SCAN,
            ResearchScope.ANALYST_SENTIMENT,
            ResearchScope.GENERAL_QUESTION,
            ResearchScope.COMPANY_OVERVIEW,
            ResearchScope.FINANCIAL_FILING_REVIEW,
        ],
    )
    def test_every_scope_rejects_an_over_long_normalized_query(self, scope: ResearchScope) -> None:
        kwargs: dict = {"original_question": "x" * 2001, "scope": scope}
        if scope != ResearchScope.GENERAL_QUESTION:
            kwargs["subject_raw_text"] = "Acme Corp"
        if scope in (ResearchScope.COMPANY_OVERVIEW, ResearchScope.FINANCIAL_FILING_REVIEW):
            kwargs["sec_cik"] = "320193"
        if scope == ResearchScope.COMPANY_OVERVIEW:
            kwargs["sec_concepts"] = ["Assets"]
        with pytest.raises(ValidationError):
            LiveResearchRunExecutionParameters(**kwargs)

    def test_a_filing_question_accepted_here_is_short_enough_for_the_domain_model(self) -> None:
        # The point of enforcing the boundary at parameter-validation
        # time: anything this model accepts must be constructible as a
        # real `ResearchRequest`, so `submit_request` can never fail on
        # `normalized_query` after a job row already exists.
        params = _filing_params(original_question="x" * 2000)
        request = ResearchRequest(
            # `ResearchRequest` independently requires exactly one trusted
            # requester - the same rule the handler now enforces on its
            # `JobExecutionContext` before ever reaching this model.
            requested_by_account_id=uuid4(),
            original_question=params.original_question,
            normalized_query=normalize_query(params.original_question),
            subject_raw_text=params.subject_raw_text, scope=params.scope,
            idempotency_key="k1", request_hash="0" * 64,
        )
        assert len(request.normalized_query) == 2000


class TestDiscoveryQuestionLengthBoundary:
    """G2B Correction V2, item 4 (unchanged, and still separately
    required): the query actually *transmitted* to the discovery provider
    is the un-normalized question, bounded by
    `DiscoverySearchRequest.query`'s own max_length=2000, for every scope
    that calls discovery search."""

    @pytest.mark.parametrize(
        "scope", [ResearchScope.NEWS_SCAN, ResearchScope.ANALYST_SENTIMENT, ResearchScope.GENERAL_QUESTION, ResearchScope.COMPANY_OVERVIEW]
    )
    def test_2001_character_question_is_rejected(self, scope: ResearchScope) -> None:
        kwargs: dict = {"original_question": "x" * 2001, "scope": scope}
        if scope != ResearchScope.GENERAL_QUESTION:
            kwargs["subject_raw_text"] = "Acme Corp"
        if scope == ResearchScope.COMPANY_OVERVIEW:
            kwargs["sec_cik"] = "320193"
            kwargs["sec_concepts"] = ["Assets"]
        with pytest.raises(ValidationError):
            LiveResearchRunExecutionParameters(**kwargs)

    def test_2000_character_question_is_accepted_at_the_boundary(self) -> None:
        params = _params(scope=ResearchScope.NEWS_SCAN, original_question="x" * 2000, subject_raw_text="Acme Corp")
        assert len(params.original_question) == 2000

    @pytest.mark.parametrize(
        "scope", [ResearchScope.NEWS_SCAN, ResearchScope.ANALYST_SENTIMENT, ResearchScope.GENERAL_QUESTION, ResearchScope.COMPANY_OVERVIEW]
    )
    def test_2001_transmitted_characters_are_rejected_even_when_normalization_would_fit(self, scope: ResearchScope) -> None:
        """The discovery boundary applies to the transmitted question, so
        a question that normalizes to exactly 2000 is still rejected when
        the string actually sent to the provider is 2001 characters."""
        assert len(_TRANSMITTED_2001_NORMALIZED_2000) == 2001
        assert len(normalize_query(_TRANSMITTED_2001_NORMALIZED_2000)) == 2000

        kwargs: dict = {"original_question": _TRANSMITTED_2001_NORMALIZED_2000, "scope": scope}
        if scope != ResearchScope.GENERAL_QUESTION:
            kwargs["subject_raw_text"] = "Acme Corp"
        if scope == ResearchScope.COMPANY_OVERVIEW:
            kwargs["sec_cik"] = "320193"
            kwargs["sec_concepts"] = ["Assets"]
        with pytest.raises(ValidationError):
            LiveResearchRunExecutionParameters(**kwargs)

    def test_filing_review_is_exempt_from_the_transmitted_bound_only(self) -> None:
        """What FINANCIAL_FILING_REVIEW is (and is not) exempt from: it
        never builds a `DiscoverySearchRequest`, so the *transmitted*
        2000-character bound does not apply to it - but the normalized
        `ResearchRequest` bound still does (see
        `TestNormalizedQueryBoundary`)."""
        params = _filing_params(original_question=_TRANSMITTED_2001_NORMALIZED_2000)
        assert len(params.original_question) == 2001
        assert len(normalize_query(params.original_question)) == 2000


class TestWhitespaceNormalizationIsExplicitAndDeterministic:
    """Exactly which transformation the boundary above is computed on:
    `domain.live_research.hashing.normalize_query` - strip the ends,
    collapse every internal whitespace run to a single space, lowercase.
    The stored `original_question` keeps its internal whitespace (only
    its ends are stripped), so the two lengths differ deliberately."""

    @pytest.mark.parametrize(
        "raw,expected_normalized",
        [
            ("What is a bond?", "what is a bond?"),
            ("  What is a bond?  ", "what is a bond?"),
            ("What  is   a bond?", "what is a bond?"),
            ("What\tis\na bond?", "what is a bond?"),
            ("What \t\n is a bond?", "what is a bond?"),
            ("WHAT IS A BOND?", "what is a bond?"),
            ("What Is A BOND?", "what is a bond?"),
        ],
    )
    def test_normalization_is_exactly_strip_collapse_lowercase(self, raw: str, expected_normalized: str) -> None:
        params = _params(original_question=raw)
        assert normalize_query(params.original_question) == expected_normalized

    def test_original_question_keeps_internal_whitespace_while_normalization_collapses_it(self) -> None:
        params = _params(original_question="  What  is   a bond?  ")
        assert params.original_question == "What  is   a bond?"
        assert normalize_query(params.original_question) == "what is a bond?"
        assert len(normalize_query(params.original_question)) < len(params.original_question)

    def test_lowercasing_never_changes_the_measured_length(self) -> None:
        upper = _params(original_question="A" * 2000, scope=ResearchScope.NEWS_SCAN, subject_raw_text="Acme Corp")
        assert len(normalize_query(upper.original_question)) == 2000

    def test_collapsing_is_what_lets_a_2001_character_question_normalize_to_2000(self) -> None:
        # Same construction the boundary tests above rely on, stated
        # directly so the arithmetic is not implicit anywhere: one
        # two-space run collapses to one space, saving exactly one
        # character.
        assert len(_TRANSMITTED_2001_NORMALIZED_2000) == 2001
        assert normalize_query(_TRANSMITTED_2001_NORMALIZED_2000) == "x" * 1998 + " " + "y"
        assert len(normalize_query(_TRANSMITTED_2001_NORMALIZED_2000)) == 2000

    def test_normalization_is_deterministic_across_repeated_construction(self) -> None:
        raw = "  What   IS a\tBond?  "
        results = {normalize_query(_params(original_question=raw).original_question) for _ in range(5)}
        assert results == {"what is a bond?"}

    def test_a_question_that_only_fits_after_collapsing_is_accepted_for_a_filing_review(self) -> None:
        # 2002 transmitted characters, exactly 2000 after collapsing the
        # single three-space run: accepted, because the boundary is
        # measured on the normalized form.
        raw = "x" * 1000 + "   " + "y" * 999
        params = _filing_params(original_question=raw)
        assert len(params.original_question) == 2002
        assert len(normalize_query(params.original_question)) == 2000

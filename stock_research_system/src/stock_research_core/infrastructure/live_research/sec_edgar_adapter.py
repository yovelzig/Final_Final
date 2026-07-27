"""SEC EDGAR public data API adapter (Phase G2A1), satisfying
`OfficialCompanyDataProviderPort`.

Calls only SEC EDGAR's public, unauthenticated JSON data endpoints:

- `GET {base_url}/submissions/CIK##########.json`
- `GET {base_url}/api/xbrl/companyfacts/CIK##########.json`

No `Authorization` header and no API key are ever sent - SEC EDGAR's
public data APIs require only a declared, contactable `User-Agent`. This
adapter never calls the (authenticated, filer-facing) EDGAR
filing/submission API.

Tests must inject an `httpx.AsyncClient` built on `httpx.MockTransport` -
this adapter makes no network call during construction, and none during
the unit suite. There are no automatic retries here; retry policy belongs
to a later phase (G2B).

Request pacing is per-process only: `_RequestPacer` enforces a minimum
interval between the requests *this adapter instance* makes, using an
injectable clock/sleep so unit tests never wait in real time. It does not
coordinate across worker processes - G2B is expected to additionally
route Live Research SEC calls through a bounded worker/queue
configuration so aggregate, cross-process request volume stays within
SEC's fair-access guidance.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from stock_research_core.application.exceptions import LiveResearchProviderConfigurationError, LiveResearchProviderResponseError
from stock_research_core.application.live_research.provider_models import (
    ExternalEvidenceCandidate,
    ProviderFetchResult,
    SecCompanyFactsRequest,
    SecSubmissionsRequest,
)
from stock_research_core.domain.live_research.enums import EvidenceClassification, SourceType
from stock_research_core.infrastructure.live_research._http import execute_request, parse_json_body
from stock_research_core.infrastructure.live_research.config import (
    _MAX_SEC_REQUESTS_PER_SECOND,
    _MAX_SEC_USER_AGENT_LENGTH,
    _contains_control_characters,
    _looks_like_declared_identity,
    _normalize_https_base_url,
    _require_finite_positive,
)

_PROVIDER_NAME = "sec_edgar"
_SEC_PUBLISHER = "U.S. Securities and Exchange Commission"
_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"

_REQUIRED_RECENT_COLUMNS = ("accessionNumber", "filingDate", "form")
_OPTIONAL_RECENT_COLUMNS = ("acceptanceDateTime", "primaryDocument", "reportDate")

# ASCII-only ([0-9], not \d) so a Unicode digit character (e.g. an
# Arabic-Indic digit, which both `str.isdigit()` and bare `\d` would
# accept) can never be mistaken for part of a CIK or accession number.
_RESPONSE_CIK_PATTERN = re.compile(r"^[0-9]{1,10}$")
_ACCESSION_NUMBER_PATTERN = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
_TEN_DIGIT_CIK_PATTERN = re.compile(r"^[0-9]{10}$")

_UNIT_MAX_LENGTH = 50
_FORM_MAX_LENGTH = 20
_FISCAL_PERIOD_MAX_LENGTH = 20
_FRAME_MAX_LENGTH = 100
_MAX_PRIMARY_DOCUMENT_LENGTH = 255


def _normalize_response_cik(value: Any) -> str | None:
    """Strictly normalizes an SEC response's top-level `cik` field to
    exactly ten ASCII digits, or returns `None` if it is not usable.
    Accepts an `int` or an ASCII-digit-only `str` matching
    `^[0-9]{1,10}$`; rejects `bool` (a `bool` is an `int` subclass in
    Python), zero, negative values, non-ASCII-digit content (including
    Unicode digit characters), and values longer than ten digits."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        digits = str(value)
    elif isinstance(value, str):
        digits = value.strip()
    else:
        return None
    if not _RESPONSE_CIK_PATTERN.match(digits):
        return None
    if int(digits) == 0:
        return None
    return digits.zfill(10)


def _validate_response_cik(body: dict[str, Any], *, expected_cik: str, endpoint_category: str) -> None:
    """Requires the response's top-level `cik` to normalize successfully
    and match the CIK that was actually requested. Never includes the
    upstream payload in the raised message."""
    normalized = _normalize_response_cik(body.get("cik"))
    if normalized is None:
        raise LiveResearchProviderResponseError(
            f"{_PROVIDER_NAME}: {endpoint_category} response is missing a valid top-level 'cik'"
        )
    if normalized != expected_cik:
        raise LiveResearchProviderResponseError(
            f"{_PROVIDER_NAME}: {endpoint_category} response 'cik' does not match the requested cik"
        )


class _RequestPacer:
    """Enforces a minimum interval between successive requests made by one
    adapter instance, safely across concurrent async callers.

    `clock`/`sleep` are injected so tests never wait in real time (a fake
    clock + a controllable `sleep` make pacing fully deterministic). An
    internal `asyncio.Lock` is held across the calculation, the optional
    sleep, and the timestamp update as a single critical section, so two
    concurrent callers can never both compute a "no wait needed" slot
    against the same stale `_last_request_at` value. The lock is never
    held during the HTTP response itself - only `wait_for_slot()` is
    guarded; the request/response happens entirely after it returns.
    """

    def __init__(
        self,
        *,
        requests_per_second: float,
        clock: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        if isinstance(requests_per_second, bool):
            raise LiveResearchProviderConfigurationError("sec_edgar: requests_per_second must not be a bool")
        if not math.isfinite(requests_per_second) or requests_per_second <= 0:
            raise LiveResearchProviderConfigurationError(
                "sec_edgar: requests_per_second must be finite and greater than zero"
            )
        if requests_per_second > _MAX_SEC_REQUESTS_PER_SECOND:
            raise LiveResearchProviderConfigurationError(
                f"sec_edgar: requests_per_second must not exceed {_MAX_SEC_REQUESTS_PER_SECOND}"
            )
        self._min_interval_seconds = 1.0 / requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._lock = asyncio.Lock()

    async def wait_for_slot(self) -> None:
        async with self._lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._min_interval_seconds - (now - self._last_request_at)
                if remaining > 0:
                    await self._sleep(remaining)
            self._last_request_at = self._clock()


def _safe_str(column: list[Any] | None, index: int) -> str | None:
    if column is None or index >= len(column):
        return None
    value = column[index]
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


# Exact ASCII shape - `[0-9]`, not `\d`, so a Unicode digit character can
# never satisfy the shape check; only after this match may `strptime` be
# called (to reject impossible calendar dates like month 13 or day 40).
_SEC_DATE_SHAPE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _parse_sec_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    if "T" not in value:
        return None  # a bare date is not a valid acceptance timestamp - it must include a time component
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_sec_date(value: str | None) -> datetime | None:
    if not value:
        return None
    if not _SEC_DATE_SHAPE_PATTERN.match(value):
        return None  # rejects "2024-1-1", "2024-01-1", "2024-1-01", and Unicode-digit dates
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None  # rejects impossible calendar dates (e.g. month 13, day 40)
    return parsed.replace(tzinfo=timezone.utc)


def _extract_recent_filings_columns(body: Any, *, expected_cik: str) -> tuple[dict[str, list[Any]], str]:
    if not isinstance(body, dict):
        raise LiveResearchProviderResponseError(f"{_PROVIDER_NAME}: submissions response is not a JSON object")
    _validate_response_cik(body, expected_cik=expected_cik, endpoint_category="submissions")
    entity_name = body.get("entityName")
    if not isinstance(entity_name, str) or not entity_name.strip():
        raise LiveResearchProviderResponseError(f"{_PROVIDER_NAME}: submissions response is missing 'entityName'")
    filings = body.get("filings")
    if not isinstance(filings, dict):
        raise LiveResearchProviderResponseError(f"{_PROVIDER_NAME}: submissions response is missing 'filings'")
    recent = filings.get("recent")
    if not isinstance(recent, dict):
        raise LiveResearchProviderResponseError(f"{_PROVIDER_NAME}: submissions response is missing 'filings.recent'")

    columns: dict[str, list[Any]] = {}
    for name in (*_REQUIRED_RECENT_COLUMNS, *_OPTIONAL_RECENT_COLUMNS):
        value = recent.get(name)
        if value is None:
            continue
        if not isinstance(value, list):
            raise LiveResearchProviderResponseError(
                f"{_PROVIDER_NAME}: submissions 'filings.recent.{name}' is not an array"
            )
        columns[name] = value

    for name in _REQUIRED_RECENT_COLUMNS:
        if name not in columns:
            raise LiveResearchProviderResponseError(
                f"{_PROVIDER_NAME}: submissions 'filings.recent' is missing required column '{name}'"
            )

    lengths = {len(values) for values in columns.values()}
    if len(lengths) > 1:
        raise LiveResearchProviderResponseError(
            f"{_PROVIDER_NAME}: submissions 'filings.recent' columns have mismatched lengths"
        )
    return columns, entity_name.strip()[:250]


_SAFE_DOCUMENT_NAME_PATTERN_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


def _is_safe_primary_document(value: str) -> bool:
    """A safe, bounded basename: only the approved charset, at most
    `_MAX_PRIMARY_DOCUMENT_LENGTH` characters, and never a `..` segment
    (defense in depth - the charset already excludes `/`, `\\`, `?`, and
    `#`, so a query/fragment/path-separator cannot appear)."""
    if not value or len(value) > _MAX_PRIMARY_DOCUMENT_LENGTH:
        return False
    if any(ch not in _SAFE_DOCUMENT_NAME_PATTERN_CHARS for ch in value):
        return False
    if ".." in value:
        return False
    return True


def _derive_filing_url(*, cik: str, accession_number: str, primary_document: str | None) -> str | None:
    """Derives the public filing-document URL from CIK, accession number,
    and primaryDocument. Returns `None` (never a guessed/invented URL)
    unless the requested CIK is a normalized ten-digit positive CIK, the
    accession number matches SEC's exact `^[0-9]{10}-[0-9]{2}-[0-9]{6}$`
    shape and starts with that same CIK, and primaryDocument is a safe,
    bounded basename.
    """
    if not _TEN_DIGIT_CIK_PATTERN.match(cik) or int(cik) == 0:
        return None
    if not _ACCESSION_NUMBER_PATTERN.match(accession_number) or not accession_number.startswith(cik):
        return None
    if not primary_document or not _is_safe_primary_document(primary_document):
        return None
    accession_no_dashes = accession_number.replace("-", "")
    cik_no_leading_zeros = str(int(cik))
    return f"{_ARCHIVES_BASE_URL}/{cik_no_leading_zeros}/{accession_no_dashes}/{primary_document}"


def _map_submissions(body: Any, *, cik: str, requested_forms: list[str] | None, limit: int) -> list[ExternalEvidenceCandidate]:
    columns, entity_name = _extract_recent_filings_columns(body, expected_cik=cik)
    row_count = len(columns[_REQUIRED_RECENT_COLUMNS[0]])
    forms_filter = set(requested_forms) if requested_forms else None

    candidates: list[ExternalEvidenceCandidate] = []
    for index in range(row_count):
        if len(candidates) >= limit:
            break

        form = _safe_str(columns.get("form"), index)
        accession_number = _safe_str(columns.get("accessionNumber"), index)
        filing_date_raw = _safe_str(columns.get("filingDate"), index)
        if form is None or accession_number is None or filing_date_raw is None:
            continue  # malformed row: a required column's value is missing/blank at this index

        filing_date_parsed = _parse_sec_date(filing_date_raw)
        if filing_date_parsed is None:
            continue  # filingDate is required and must parse as YYYY-MM-DD

        if not _ACCESSION_NUMBER_PATTERN.match(accession_number) or not accession_number.startswith(cik):
            # accessionNumber is the required filing identity for an
            # official filing candidate - a malformed shape or a prefix
            # that doesn't belong to the requested CIK is never allowed
            # to become official evidence; skip the row rather than
            # record it with a malformed/mismatched identifier.
            continue

        normalized_form = form.upper()
        if len(normalized_form) > _FORM_MAX_LENGTH:
            continue  # form is bounded - an oversized value is malformed
        if forms_filter is not None and normalized_form not in forms_filter:
            continue

        acceptance_date_time_raw = _safe_str(columns.get("acceptanceDateTime"), index)
        acceptance_date_time_parsed = (
            _parse_sec_datetime(acceptance_date_time_raw) if acceptance_date_time_raw is not None else None
        )
        primary_document = _safe_str(columns.get("primaryDocument"), index)
        primary_document_is_safe = primary_document is not None and _is_safe_primary_document(primary_document)
        report_date_raw = _safe_str(columns.get("reportDate"), index)
        report_date_parsed = _parse_sec_date(report_date_raw) if report_date_raw is not None else None

        published_at = acceptance_date_time_parsed or filing_date_parsed
        source_url = _derive_filing_url(cik=cik, accession_number=accession_number, primary_document=primary_document)

        structured_facts: dict[str, Any] = {
            "accession_number": accession_number,
            "form": normalized_form,
            "filing_date": filing_date_raw,
        }
        if acceptance_date_time_parsed is not None:
            structured_facts["acceptance_date_time"] = acceptance_date_time_raw
        if report_date_parsed is not None:
            structured_facts["report_date"] = report_date_raw
        if primary_document_is_safe:
            # Unsafe or oversized primaryDocument suppresses both the URL
            # (already handled by `_derive_filing_url`) and this field -
            # the otherwise-valid filing row itself may still remain.
            structured_facts["primary_document"] = primary_document

        try:
            candidate = ExternalEvidenceCandidate(
                source_type=SourceType.SEC_OFFICIAL_FILING,
                classification=EvidenceClassification.OFFICIAL,
                source_url=source_url,
                official_identifier=accession_number,
                source_title=f"{entity_name} - {normalized_form} filing"[:1000],
                publisher=_SEC_PUBLISHER,
                published_at=published_at,
                raw_excerpt=None,
                normalized_text=None,
                structured_facts=structured_facts,
                provider_metadata={"provider": _PROVIDER_NAME, "endpoint": "submissions"},
            )
        except ValueError:
            continue
        candidates.append(candidate)
    return candidates


def _validate_company_facts_top_level(body: Any, *, expected_cik: str) -> tuple[str, dict[str, Any]]:
    if not isinstance(body, dict):
        raise LiveResearchProviderResponseError(f"{_PROVIDER_NAME}: companyfacts response is not a JSON object")
    _validate_response_cik(body, expected_cik=expected_cik, endpoint_category="companyfacts")
    entity_name = body.get("entityName")
    if not isinstance(entity_name, str) or not entity_name.strip():
        raise LiveResearchProviderResponseError(f"{_PROVIDER_NAME}: companyfacts response is missing 'entityName'")
    facts = body.get("facts")
    if not isinstance(facts, dict):
        raise LiveResearchProviderResponseError(f"{_PROVIDER_NAME}: companyfacts response is missing 'facts'")
    return entity_name.strip()[:250], facts


def _parse_fact_observation(
    entry: Any, *, unit: str, forms_filter: set[str], expected_cik: str
) -> tuple[tuple[datetime, datetime], dict[str, Any]] | None:
    if not isinstance(entry, dict):
        return None

    unit_stripped = unit.strip()
    if not unit_stripped or len(unit_stripped) > _UNIT_MAX_LENGTH or _contains_control_characters(unit_stripped):
        return None

    val = entry.get("val")
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        return None  # never convert a missing value into 0
    if isinstance(val, float) and not math.isfinite(val):
        return None  # reject NaN and +/-Infinity

    accn = entry.get("accn")
    if not isinstance(accn, str) or not accn.strip():
        return None
    accn_stripped = accn.strip()
    if not _ACCESSION_NUMBER_PATTERN.match(accn_stripped) or not accn_stripped.startswith(expected_cik):
        return None  # malformed or CIK-mismatched accession - never becomes official evidence

    form = entry.get("form")
    if not isinstance(form, str) or not form.strip():
        return None
    normalized_form = form.strip().upper()
    if len(normalized_form) > _FORM_MAX_LENGTH or _contains_control_characters(normalized_form):
        return None
    if normalized_form not in forms_filter:
        return None

    end_raw = entry.get("end")
    if not isinstance(end_raw, str) or not end_raw.strip():
        return None
    end_parsed = _parse_sec_date(end_raw.strip())
    if end_parsed is None:
        return None  # end is required and must parse as YYYY-MM-DD

    filed_raw = entry.get("filed")
    filed_parsed: datetime | None = None
    if filed_raw is not None:
        if not isinstance(filed_raw, str) or not filed_raw.strip():
            return None
        filed_parsed = _parse_sec_date(filed_raw.strip())
        if filed_parsed is None:
            return None  # filed, when present, must parse as YYYY-MM-DD

    start_raw = entry.get("start")
    start_parsed: datetime | None = None
    if start_raw is not None:
        if not isinstance(start_raw, str) or not start_raw.strip():
            return None
        start_parsed = _parse_sec_date(start_raw.strip())
        if start_parsed is None:
            return None  # start, when present, must parse as YYYY-MM-DD
        if start_parsed > end_parsed:
            return None  # reject start later than end

    fy = entry.get("fy") if isinstance(entry.get("fy"), int) and not isinstance(entry.get("fy"), bool) else None

    fp_raw = entry.get("fp")
    fp: str | None = None
    if fp_raw is not None:
        if not isinstance(fp_raw, str):
            return None
        fp_stripped = fp_raw.strip()
        if (
            not fp_stripped
            or len(fp_stripped) > _FISCAL_PERIOD_MAX_LENGTH
            or _contains_control_characters(fp_stripped)
        ):
            return None  # do not silently truncate - reject the whole observation
        fp = fp_stripped

    frame_raw = entry.get("frame")
    frame: str | None = None
    if frame_raw is not None:
        if not isinstance(frame_raw, str):
            return None
        frame_stripped = frame_raw.strip()
        if (
            not frame_stripped
            or len(frame_stripped) > _FRAME_MAX_LENGTH
            or _contains_control_characters(frame_stripped)
        ):
            return None  # do not silently truncate - reject the whole observation
        frame = frame_stripped

    sort_key = (end_parsed, filed_parsed or datetime.min.replace(tzinfo=timezone.utc))
    observation = {
        "unit": unit_stripped,
        "value": val,
        "accession_number": accn_stripped,
        "form": normalized_form,
        "fiscal_year": fy,
        "fiscal_period": fp,
        "filed_date": filed_raw.strip() if filed_parsed is not None else None,
        "start": start_raw.strip() if start_parsed is not None else None,
        "end": end_raw.strip(),
        "frame": frame,
    }
    return sort_key, observation


def _compute_company_fact_identifier(
    *,
    taxonomy: str,
    concept: str,
    unit: str,
    accession_number: str,
    start: str | None,
    end: str,
    frame: str | None,
) -> str:
    """A deterministic identifier that incorporates every field that
    distinguishes one reporting context from another (taxonomy, concept,
    unit, accession number, start, end, frame) via a stable SHA-256 hash
    of a canonical JSON serialization, so two observations differing only
    in `start` or `frame` never collide - and no delimiter-joined string
    can ever create ambiguity from an embedded delimiter character.
    Always well within the 200-character bound.
    """
    canonical_payload = {
        "taxonomy": taxonomy,
        "concept": concept,
        "unit": unit,
        "accession_number": accession_number,
        "start": start,
        "end": end,
        "frame": frame,
    }
    canonical = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"cf:{digest}"


def _build_company_fact_candidate(
    *,
    entity_name: str,
    taxonomy: str,
    concept: str,
    label: str | None,
    description: str | None,
    observation: dict[str, Any],
) -> ExternalEvidenceCandidate | None:
    accession_number = observation["accession_number"]
    official_identifier = _compute_company_fact_identifier(
        taxonomy=taxonomy,
        concept=concept,
        unit=observation["unit"],
        accession_number=accession_number,
        start=observation["start"],
        end=observation["end"],
        frame=observation["frame"],
    )

    structured_facts: dict[str, Any] = {
        "taxonomy": taxonomy,
        "concept": concept,
        "unit": observation["unit"],
        "value": observation["value"],
        "accession_number": accession_number,
        "form": observation["form"],
        "fiscal_year": observation["fiscal_year"],
        "fiscal_period": observation["fiscal_period"],
        "filed_date": observation["filed_date"],
        "start": observation["start"],
        "end": observation["end"],
        "frame": observation["frame"],
    }
    if label:
        structured_facts["label"] = label[:500]
    if description:
        structured_facts["description"] = description[:2000]

    published_at = _parse_sec_date(observation["filed_date"]) if observation["filed_date"] else None

    try:
        return ExternalEvidenceCandidate(
            source_type=SourceType.EXCHANGE_REGULATOR_GOVERNMENT,
            classification=EvidenceClassification.OFFICIAL,
            source_url=None,
            official_identifier=official_identifier,
            source_title=f"{entity_name} - {concept} ({observation['form']})"[:1000],
            publisher=_SEC_PUBLISHER,
            published_at=published_at,
            raw_excerpt=None,
            normalized_text=None,
            structured_facts=structured_facts,
            provider_metadata={"provider": _PROVIDER_NAME, "endpoint": "companyfacts"},
        )
    except ValueError:
        return None


def _map_company_facts(body: Any, *, request: SecCompanyFactsRequest) -> list[ExternalEvidenceCandidate]:
    entity_name, facts = _validate_company_facts_top_level(body, expected_cik=request.cik)

    taxonomy_data = facts.get(request.taxonomy)
    if not isinstance(taxonomy_data, dict):
        return []

    forms_filter = set(request.forms)
    candidates: list[ExternalEvidenceCandidate] = []

    for concept in request.concepts:
        concept_data = taxonomy_data.get(concept)
        if not isinstance(concept_data, dict):
            continue
        units = concept_data.get("units")
        if not isinstance(units, dict):
            continue
        label = concept_data.get("label") if isinstance(concept_data.get("label"), str) else None
        description = concept_data.get("description") if isinstance(concept_data.get("description"), str) else None

        observations: list[tuple[tuple[datetime, datetime], dict[str, Any]]] = []
        for unit, entries in units.items():
            if not isinstance(unit, str) or not isinstance(entries, list):
                continue
            for entry in entries:
                parsed = _parse_fact_observation(entry, unit=unit, forms_filter=forms_filter, expected_cik=request.cik)
                if parsed is not None:
                    observations.append(parsed)

        observations.sort(key=lambda item: item[0], reverse=True)
        accepted = observations[: request.max_facts_per_concept]

        for _, observation in accepted:
            candidate = _build_company_fact_candidate(
                entity_name=entity_name,
                taxonomy=request.taxonomy,
                concept=concept,
                label=label,
                description=description,
                observation=observation,
            )
            if candidate is not None:
                candidates.append(candidate)
    return candidates


class SecEdgarAdapter:
    """Calls SEC EDGAR's public `submissions` and `companyfacts` JSON APIs.
    Satisfies `OfficialCompanyDataProviderPort`."""

    provider_name = _PROVIDER_NAME

    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        timeout_seconds: float = 30.0,
        requests_per_second: float = 5.0,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        try:
            normalized_base_url = _normalize_https_base_url("sec_edgar: base_url", base_url)
        except ValueError as exc:
            raise LiveResearchProviderConfigurationError(str(exc)) from exc

        declared_identity = user_agent.strip()
        if len(declared_identity) > _MAX_SEC_USER_AGENT_LENGTH:
            raise LiveResearchProviderConfigurationError(
                f"sec_edgar: user_agent must be at most {_MAX_SEC_USER_AGENT_LENGTH} characters"
            )
        if _contains_control_characters(declared_identity):
            raise LiveResearchProviderConfigurationError("sec_edgar: user_agent must not contain control characters")
        if not declared_identity:
            raise LiveResearchProviderConfigurationError("sec_edgar: user_agent must not be empty")
        if not _looks_like_declared_identity(declared_identity):
            raise LiveResearchProviderConfigurationError(
                "sec_edgar: user_agent must declare a product/company identity and contact information "
                "(an email address or a URL)"
            )
        try:
            _require_finite_positive("sec_edgar: timeout_seconds", timeout_seconds)
        except ValueError as exc:
            raise LiveResearchProviderConfigurationError(str(exc)) from exc

        self._base_url = normalized_base_url
        self._user_agent = declared_identity
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        # `_RequestPacer` itself validates requests_per_second is finite,
        # positive, and <= the shared SEC bound - reused rather than
        # duplicated here.
        self._pacer = _RequestPacer(requests_per_second=requests_per_second, clock=clock, sleep=sleep)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        }

    async def fetch_submissions(self, request: SecSubmissionsRequest) -> ProviderFetchResult:
        await self._pacer.wait_for_slot()
        url = f"{self._base_url}/submissions/CIK{request.cik}.json"
        response = await execute_request(
            self._client,
            "GET",
            url,
            provider=_PROVIDER_NAME,
            endpoint_category="submissions",
            headers=self._headers(),
        )
        body = parse_json_body(response, provider=_PROVIDER_NAME, endpoint_category="submissions")
        candidates = _map_submissions(body, cik=request.cik, requested_forms=request.forms, limit=request.limit)
        return ProviderFetchResult(
            provider_name=_PROVIDER_NAME,
            provider_request_id=None,
            fetched_at=datetime.now(timezone.utc),
            candidates=candidates,
            metadata={},
        )

    async def fetch_company_facts(self, request: SecCompanyFactsRequest) -> ProviderFetchResult:
        await self._pacer.wait_for_slot()
        url = f"{self._base_url}/api/xbrl/companyfacts/CIK{request.cik}.json"
        response = await execute_request(
            self._client,
            "GET",
            url,
            provider=_PROVIDER_NAME,
            endpoint_category="companyfacts",
            headers=self._headers(),
        )
        body = parse_json_body(response, provider=_PROVIDER_NAME, endpoint_category="companyfacts")
        candidates = _map_company_facts(body, request=request)
        return ProviderFetchResult(
            provider_name=_PROVIDER_NAME,
            provider_request_id=None,
            fetched_at=datetime.now(timezone.utc),
            candidates=candidates,
            metadata={},
        )

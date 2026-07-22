"""Generic offset-pagination foundation shared by every list endpoint that
needs it (spec ss19: default limit 20, maximum 100, non-negative offset).

Applied only to genuinely growable collections (mastery/progress/
misconceptions, portfolios, transactions, journal entries, tutor
conversations, admin accounts/documents/gaps/audit-events) - small,
fixed-size catalogs (learning paths, modules, lessons, exercises) are
returned as plain lists per spec's "do not paginate small fixed
collections unnecessarily."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from fastapi import Query

from stock_research_core.api.schemas.common import PaginatedResponse, PaginationMeta

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

T = TypeVar("T")


@dataclass(frozen=True)
class PaginationParams:
    limit: int
    offset: int


def pagination_params(
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Maximum items to return."),
    offset: int = Query(default=0, ge=0, description="Number of items to skip."),
) -> PaginationParams:
    return PaginationParams(limit=limit, offset=offset)


def paginated(*, items: list[T], total: int, params: PaginationParams) -> PaginatedResponse[T]:
    return PaginatedResponse(
        items=items,
        pagination=PaginationMeta(limit=params.limit, offset=params.offset, returned=len(items), total=total),
    )

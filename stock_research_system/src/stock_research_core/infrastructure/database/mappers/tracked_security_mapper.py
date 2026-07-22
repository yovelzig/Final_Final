"""Maps between `TrackedSecurityORM` rows and the `TrackedSecurity` domain model."""

from __future__ import annotations

from pydantic import ValidationError

from stock_research_core.application.exceptions import DatabaseMappingError
from stock_research_core.domain.models import TrackedSecurity
from stock_research_core.infrastructure.database.orm.tracked_security import TrackedSecurityORM


def tracked_security_orm_to_domain(row: TrackedSecurityORM) -> TrackedSecurity:
    """Map a stored `TrackedSecurityORM` row to a validated `TrackedSecurity` domain object."""
    try:
        return TrackedSecurity(
            security_id=row.security_id,
            enabled=row.enabled,
            monitoring_started_at=row.monitoring_started_at,
            last_successful_update_at=row.last_successful_update_at,
            next_scheduled_update_at=row.next_scheduled_update_at,
            alert_threshold_probability_change=float(row.alert_threshold_probability_change),
            alert_threshold_expected_return_change=float(
                row.alert_threshold_expected_return_change
            ),
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise DatabaseMappingError(
            f"Stored tracked-security row '{row.security_id}' could not be mapped "
            f"to a domain TrackedSecurity."
        ) from exc

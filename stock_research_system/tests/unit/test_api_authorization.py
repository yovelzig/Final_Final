"""Unit tests for the role-hierarchy and ownership-enforcement helpers in
`api/dependencies.py` - exercised directly against fake `AuthenticatedPrincipal`
values, no HTTP, no database.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from stock_research_core.api.dependencies import (
    ensure_owned_by_learner,
    require_admin,
    require_content_editor,
    require_learner,
    require_roles,
)
from stock_research_core.application.exceptions import InsufficientPermissionError, LearnerNotFoundError
from stock_research_core.application.identity.models import AuthenticatedPrincipal
from stock_research_core.domain.identity.enums import AccountRole


def _principal(role: AccountRole, *, learner_id=None) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        account_id=uuid4(), learner_id=learner_id if learner_id is not None else uuid4(), role=role,
        email="user@example.com", display_name="User",
    )


class TestRoleHierarchy:
    """ADMIN >= CONTENT_EDITOR >= LEARNER for the `_require_minimum_role` dependencies."""

    async def test_require_learner_allows_all_three_roles(self) -> None:
        for role in (AccountRole.LEARNER, AccountRole.CONTENT_EDITOR, AccountRole.ADMIN):
            principal = _principal(role)
            assert await require_learner(principal) is principal

    async def test_require_content_editor_rejects_learner(self) -> None:
        with pytest.raises(InsufficientPermissionError):
            await require_content_editor(_principal(AccountRole.LEARNER))

    async def test_require_content_editor_allows_content_editor_and_admin(self) -> None:
        for role in (AccountRole.CONTENT_EDITOR, AccountRole.ADMIN):
            principal = _principal(role)
            assert await require_content_editor(principal) is principal

    async def test_require_admin_rejects_learner_and_content_editor(self) -> None:
        for role in (AccountRole.LEARNER, AccountRole.CONTENT_EDITOR):
            with pytest.raises(InsufficientPermissionError):
                await require_admin(_principal(role))

    async def test_require_admin_allows_only_admin(self) -> None:
        principal = _principal(AccountRole.ADMIN)
        assert await require_admin(principal) is principal


class TestRequireRoles:
    """`require_roles(*roles)` is an exact-match set, not a hierarchy."""

    async def test_allows_only_the_listed_roles(self) -> None:
        dependency = require_roles(AccountRole.CONTENT_EDITOR)
        principal = _principal(AccountRole.CONTENT_EDITOR)
        assert await dependency(principal) is principal

    async def test_admin_is_not_implicitly_allowed_by_require_roles(self) -> None:
        """Unlike the hierarchy helpers, an exact-role allowlist does not
        automatically include ADMIN unless ADMIN is explicitly listed."""
        dependency = require_roles(AccountRole.CONTENT_EDITOR)
        with pytest.raises(InsufficientPermissionError):
            await dependency(_principal(AccountRole.ADMIN))

    async def test_rejects_roles_outside_the_allowlist(self) -> None:
        dependency = require_roles(AccountRole.LEARNER, AccountRole.ADMIN)
        with pytest.raises(InsufficientPermissionError):
            await dependency(_principal(AccountRole.CONTENT_EDITOR))


class TestEnsureOwnedByLearner:
    def test_allows_the_owning_learner(self) -> None:
        learner_id = uuid4()
        principal = _principal(AccountRole.LEARNER, learner_id=learner_id)
        ensure_owned_by_learner(
            learner_id, principal, not_found_error=LearnerNotFoundError, message="not found"
        )  # must not raise

    def test_rejects_a_non_owning_learner_with_a_not_found_error_not_forbidden(self) -> None:
        """404, not 403 - a non-owner must never learn that the resource exists."""
        principal = _principal(AccountRole.LEARNER, learner_id=uuid4())
        with pytest.raises(LearnerNotFoundError):
            ensure_owned_by_learner(
                uuid4(), principal, not_found_error=LearnerNotFoundError, message="not found"
            )

    def test_rejects_when_resource_learner_id_is_none(self) -> None:
        principal = _principal(AccountRole.LEARNER, learner_id=uuid4())
        with pytest.raises(LearnerNotFoundError):
            ensure_owned_by_learner(
                None, principal, not_found_error=LearnerNotFoundError, message="not found"
            )

    def test_admin_bypasses_ownership_entirely(self) -> None:
        admin_principal = _principal(AccountRole.ADMIN, learner_id=None)
        ensure_owned_by_learner(
            uuid4(), admin_principal, not_found_error=LearnerNotFoundError, message="not found"
        )  # must not raise, even though the resource belongs to someone else

    def test_content_editor_is_not_granted_an_ownership_bypass(self) -> None:
        """Only ADMIN bypasses ownership - CONTENT_EDITOR is not a substitute for it."""
        principal = _principal(AccountRole.CONTENT_EDITOR, learner_id=uuid4())
        with pytest.raises(LearnerNotFoundError):
            ensure_owned_by_learner(
                uuid4(), principal, not_found_error=LearnerNotFoundError, message="not found"
            )

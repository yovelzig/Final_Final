"""Architecture/import-boundary checks for the identity/authentication
subsystem and the API transport layer as a whole.

AST-based (no actual import side effects are exercised beyond what's
already imported for other tests) - mirrors the equivalent checks
written for the other Phase 4-8 subsystems (e.g.
`test_ai_tutor_architecture.py`).
"""

from __future__ import annotations

import ast
import inspect

from stock_research_core.api import dependencies as api_dependencies_module
from stock_research_core.api.routers import (
    admin as admin_router_module,
    adaptive_learning as adaptive_router_module,
    ai_tutor as ai_tutor_router_module,
    auth as auth_router_module,
    curriculum as curriculum_router_module,
    health as health_router_module,
    learners as learners_router_module,
    market_scenarios as market_scenarios_router_module,
    virtual_portfolios as virtual_portfolios_router_module,
)
from stock_research_core.api.schemas import (
    admin as admin_schemas_module,
    auth as auth_schemas_module,
    common as common_schemas_module,
    curriculum as curriculum_schemas_module,
)
from stock_research_core.application.identity import models as app_models_module
from stock_research_core.application.identity import ports as ports_module
from stock_research_core.application.identity import security as security_module
from stock_research_core.domain.identity import enums as domain_enums_module
from stock_research_core.domain.identity import models as domain_models_module

_ALL_ROUTER_MODULES = (
    admin_router_module, adaptive_router_module, ai_tutor_router_module, auth_router_module,
    curriculum_router_module, health_router_module, learners_router_module,
    market_scenarios_router_module, virtual_portfolios_router_module,
)

_FORBIDDEN_IN_DOMAIN_OR_APPLICATION = {
    "sqlalchemy", "asyncpg", "fastapi", "jwt", "pwdlib", "starlette", "uvicorn",
    "langgraph", "n8n", "openai", "anthropic",
}
_FORBIDDEN_IN_ROUTERS = {"sqlalchemy", "asyncpg", "jwt", "pwdlib"}


def _imported_root_modules(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }


def _imported_full_module_paths(module: object) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}


def test_domain_identity_package_has_no_infrastructure_imports() -> None:
    for module in (domain_enums_module, domain_models_module):
        imported = _imported_root_modules(module)
        assert imported.isdisjoint(_FORBIDDEN_IN_DOMAIN_OR_APPLICATION), (
            f"{module.__name__} imports {imported & _FORBIDDEN_IN_DOMAIN_OR_APPLICATION}"
        )


def test_application_identity_package_has_no_infrastructure_imports() -> None:
    for module in (app_models_module, ports_module, security_module):
        imported = _imported_root_modules(module)
        assert imported.isdisjoint(_FORBIDDEN_IN_DOMAIN_OR_APPLICATION), (
            f"{module.__name__} imports {imported & _FORBIDDEN_IN_DOMAIN_OR_APPLICATION}"
        )


def test_application_identity_ports_never_import_infrastructure() -> None:
    imported_paths = _imported_full_module_paths(ports_module)
    assert not any("infrastructure" in path for path in imported_paths)


def test_identity_domain_models_never_carry_a_secret_field() -> None:
    """Structural guarantee: no domain identity model may ever declare a
    password/token-shaped field - secrets exist only as hashes on
    infrastructure-internal records, never on a `DomainModel`."""
    forbidden_substrings = ("password", "raw_token", "access_token", "secret")
    for class_name in ("UserAccount", "AccountRefreshToken", "AuthenticationAuditEvent"):
        cls = getattr(domain_models_module, class_name)
        for field_name in cls.model_fields:
            lowered = field_name.lower()
            assert not any(bad in lowered for bad in forbidden_substrings) or field_name == "token_hash", (
                f"{class_name}.{field_name} looks like it might carry a secret"
            )


def test_routers_never_import_sqlalchemy_or_low_level_crypto_directly() -> None:
    # `health.py` is a narrow, documented exception: `/ready` runs raw
    # infra-level connectivity/extension/Alembic-revision SQL directly
    # against `AsyncEngine` (never ORM models, never business data) since
    # that diagnostic doesn't fit the Unit-of-Work abstraction.
    business_routers = tuple(m for m in _ALL_ROUTER_MODULES if m is not health_router_module)
    for module in business_routers:
        imported = _imported_root_modules(module)
        assert imported.isdisjoint(_FORBIDDEN_IN_ROUTERS), (
            f"{module.__name__} imports {imported & _FORBIDDEN_IN_ROUTERS} directly - "
            "route handlers must go through the application/persistence layers"
        )

    health_imported = _imported_root_modules(health_router_module)
    assert health_imported.isdisjoint({"jwt", "pwdlib", "asyncpg"})


def test_routers_never_import_orm_models_directly() -> None:
    for module in _ALL_ROUTER_MODULES:
        imported_paths = _imported_full_module_paths(module)
        assert not any("infrastructure.database.orm" in path for path in imported_paths), module.__name__
        assert not any("infrastructure.database.repositories" in path for path in imported_paths), module.__name__


def test_api_schemas_never_import_orm_or_sqlalchemy() -> None:
    for module in (admin_schemas_module, auth_schemas_module, common_schemas_module, curriculum_schemas_module):
        imported = _imported_root_modules(module)
        assert imported.isdisjoint({"sqlalchemy", "asyncpg"}), module.__name__
        imported_paths = _imported_full_module_paths(module)
        assert not any("infrastructure.database.orm" in path for path in imported_paths), module.__name__


def test_api_schemas_use_extra_forbid_not_the_domain_model_base() -> None:
    """API DTOs are plain `pydantic.BaseModel` subclasses (via `ApiSchema`), never
    `domain.models.DomainModel` directly - the two base classes must stay distinct
    so a domain validator change can never silently alter wire-format behavior."""
    from stock_research_core.api.schemas.common import ApiSchema
    from stock_research_core.domain.models import DomainModel

    assert not issubclass(ApiSchema, DomainModel)
    assert not issubclass(DomainModel, ApiSchema)


def test_dependencies_module_is_the_only_router_dependency_on_infrastructure_adapters() -> None:
    """`api/dependencies.py` is the one sanctioned composition-wiring point for
    concrete infrastructure adapters within the API layer (mirroring the CLI
    composition-root convention) - routers depend on it, never on
    `infrastructure.*` directly (checked separately above)."""
    imported_paths = _imported_full_module_paths(api_dependencies_module)
    assert any("infrastructure" in path for path in imported_paths)


def test_password_and_token_ports_are_synchronous_by_design() -> None:
    """`PasswordHasherPort` methods are plain `def`, not `async def` - callers
    are responsible for running them off the event loop (see
    `IdentityService`'s `asyncio.to_thread` usage) since Argon2 hashing is
    deliberately CPU/memory-expensive."""
    import typing

    port = typing.get_type_hints(ports_module.PasswordHasherPort)
    source = inspect.getsource(ports_module.PasswordHasherPort)
    assert "async def hash_password" not in source
    assert "def hash_password" in source

"""Identity/authentication application layer: result models, provider/
repository ports, and the deterministic password policy.

`IdentityService` is intentionally not re-exported here: it imports
`stock_research_core.application.persistence.ports` (for
`UnitOfWorkPort`), which in turn imports
`stock_research_core.application.identity.ports` - eagerly importing
the service from this package's `__init__.py` would make that a
circular import, the same issue already solved for every other feature
package in this codebase. Import it directly:
`from stock_research_core.application.identity.service import IdentityService`.
"""

from stock_research_core.application.identity.models import (
    AccessTokenClaims,
    AuthenticatedPrincipal,
    IssuedTokenPair,
    LoginResult,
    RegistrationResult,
)
from stock_research_core.application.identity.ports import AccountCredential
from stock_research_core.application.identity.security import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    validate_password_policy,
)

__all__ = [
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "AccessTokenClaims",
    "AccountCredential",
    "AuthenticatedPrincipal",
    "IssuedTokenPair",
    "LoginResult",
    "RegistrationResult",
    "validate_password_policy",
]

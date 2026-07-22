"""Administrative CLI for the FinQuest identity subsystem.

Create the first ADMIN account (PowerShell):

    python -m stock_research_core.cli.identity_admin --create-admin --email admin@example.com --display-name "Admin"

(Prompts for a password via `getpass`, never echoed and never accepted
as a command-line argument, so it can never appear in shell history or
process listings.)

List accounts:

    python -m stock_research_core.cli.identity_admin --list-accounts
    python -m stock_research_core.cli.identity_admin --list-accounts --role ADMIN --status ACTIVE

Disable an account:

    python -m stock_research_core.cli.identity_admin --disable-account --email someone@example.com

Revoke every active session (refresh token) for an account:

    python -m stock_research_core.cli.identity_admin --revoke-sessions --email someone@example.com

This module is a composition root: it is the one place outside the
infrastructure layer allowed to import concrete adapters directly. It
never logs the password itself - only the resulting account ID.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from uuid import UUID

from stock_research_core.api.settings import AuthSettings
from stock_research_core.application.exceptions import DuplicateAccountError, StockResearchError
from stock_research_core.application.identity.security import validate_password_policy
from stock_research_core.application.identity.service import IdentityService
from stock_research_core.domain.identity.enums import (
    AccountRole,
    AccountStatus,
    AuthenticationEventType,
    AuthenticationResult,
)
from stock_research_core.domain.identity.models import AuthenticationAuditEvent, UserAccount
from stock_research_core.domain.models import utc_now
from stock_research_core.infrastructure.database.config import DatabaseSettings
from stock_research_core.infrastructure.database.engine import create_database_engine, create_session_factory
from stock_research_core.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from stock_research_core.infrastructure.identity.argon2_password_hasher import Argon2PasswordHasher
from stock_research_core.infrastructure.identity.jwt_access_token_service import JwtAccessTokenService
from stock_research_core.infrastructure.identity.opaque_refresh_token_service import OpaqueRefreshTokenService


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stock_research_core.cli.identity_admin",
        description="Administer FinQuest local accounts: create admins, list, disable, and revoke sessions.",
    )
    parser.add_argument("--create-admin", action="store_true", help="Create a new ADMIN account")
    parser.add_argument("--list-accounts", action="store_true", help="List accounts")
    parser.add_argument("--disable-account", action="store_true", help="Disable an account")
    parser.add_argument("--revoke-sessions", action="store_true", help="Revoke every active session for an account")

    parser.add_argument("--email", default=None, help="Account email (for --create-admin/--disable-account/--revoke-sessions)")
    parser.add_argument("--account-id", default=None, metavar="UUID", help="Account ID (alternative to --email)")
    parser.add_argument("--display-name", default=None, help="Display name (for --create-admin)")

    parser.add_argument("--role", default=None, choices=[r.value for r in AccountRole], help="Filter for --list-accounts")
    parser.add_argument("--status", default=None, choices=[s.value for s in AccountStatus], help="Filter for --list-accounts")
    parser.add_argument("--limit", type=int, default=20, help="Page size for --list-accounts (default 20)")
    parser.add_argument("--offset", type=int, default=0, help="Page offset for --list-accounts (default 0)")
    return parser


async def _resolve_account_id(uow, *, email: str | None, account_id: str | None) -> UUID:
    if account_id is not None:
        return UUID(account_id)
    if email is not None:
        account = await uow.user_accounts.get_by_normalized_email(email.strip().lower())
        if account is None:
            raise StockResearchError(f"No account found with email '{email}'.")
        return account.account_id
    raise StockResearchError("Either --email or --account-id is required.")


async def _create_admin(
    uow_factory, password_hasher: Argon2PasswordHasher, *, email: str, display_name: str
) -> None:
    normalized_email = email.strip().lower()

    password = getpass.getpass("New admin password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise StockResearchError("Passwords do not match.")
    validate_password_policy(password, normalized_email=normalized_email)

    async with uow_factory() as uow:
        if await uow.user_accounts.normalized_email_exists(normalized_email):
            raise DuplicateAccountError(f"An account with email '{email}' already exists.")

        password_hash = await asyncio.to_thread(password_hasher.hash_password, password)
        account = UserAccount(
            email=email, normalized_email=normalized_email, display_name=display_name,
            learner_id=None, role=AccountRole.ADMIN, status=AccountStatus.ACTIVE,
        )
        created = await uow.user_accounts.create_account(account=account, password_hash=password_hash)
        await uow.authentication_audit.append_event(
            AuthenticationAuditEvent(
                account_id=created.account_id, event_type=AuthenticationEventType.ACCOUNT_CREATED,
                result=AuthenticationResult.SUCCESS, correlation_id="cli-create-admin",
            )
        )
        await uow.commit()
    print(f"Created ADMIN account: {created.account_id} <{created.email}>")


async def _list_accounts(
    uow_factory, *, role: str | None, status: str | None, limit: int, offset: int
) -> None:
    async with uow_factory() as uow:
        accounts, total = await uow.user_accounts.list_accounts(
            role=AccountRole(role) if role else None, status=AccountStatus(status) if status else None,
            limit=limit, offset=offset,
        )
    print(f"{'account_id':38} {'email':40} {'role':16} {'status':10} learner_id")
    for account in accounts:
        print(
            f"{str(account.account_id):38} {account.email:40} {account.role.value:16} "
            f"{account.status.value:10} {account.learner_id or '-'}"
        )
    print(f"\n{len(accounts)} shown of {total} total (limit={limit}, offset={offset})")


async def _disable_account(uow_factory, *, email: str | None, account_id: str | None) -> None:
    async with uow_factory() as uow:
        resolved_id = await _resolve_account_id(uow, email=email, account_id=account_id)
        updated = await uow.user_accounts.update_status(
            resolved_id, status=AccountStatus.DISABLED, locked_until=None
        )
        await uow.authentication_audit.append_event(
            AuthenticationAuditEvent(
                account_id=resolved_id, event_type=AuthenticationEventType.ACCOUNT_LOCKED,
                result=AuthenticationResult.SUCCESS, correlation_id="cli-disable-account",
                reason_code="ADMIN_DISABLED",
            )
        )
        await uow.commit()
    print(f"Disabled account: {updated.account_id} <{updated.email}>")


async def _revoke_sessions(identity_service: IdentityService, uow_factory, *, email: str | None, account_id: str | None) -> None:
    async with uow_factory() as uow:
        resolved_id = await _resolve_account_id(uow, email=email, account_id=account_id)
    count = await identity_service.logout_all(account_id=resolved_id, correlation_id="cli-revoke-sessions")
    print(f"Revoked {count} active session(s) for account {resolved_id}")


async def _run(args: argparse.Namespace) -> int:
    database_settings = DatabaseSettings()
    auth_settings = AuthSettings()
    auth_settings.require_strong_secret()

    engine = create_database_engine(database_settings)
    session_factory = create_session_factory(engine)
    uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731

    password_hasher = Argon2PasswordHasher()
    identity_service = IdentityService(
        unit_of_work_factory=uow_factory,
        password_hasher=password_hasher,
        access_token_service=JwtAccessTokenService(
            secret=auth_settings.auth_jwt_secret, issuer=auth_settings.auth_jwt_issuer,
            audience=auth_settings.auth_jwt_audience, algorithm=auth_settings.auth_jwt_algorithm,
            access_token_minutes=auth_settings.auth_access_token_minutes,
        ),
        refresh_token_service=OpaqueRefreshTokenService(refresh_token_days=auth_settings.auth_refresh_token_days),
        max_failed_logins=auth_settings.auth_max_failed_logins,
        lockout_minutes=auth_settings.auth_lockout_minutes,
    )

    try:
        if args.create_admin:
            if not args.email or not args.display_name:
                print("error: --create-admin requires --email and --display-name", file=sys.stderr)
                return 2
            await _create_admin(uow_factory, password_hasher, email=args.email, display_name=args.display_name)
            return 0

        if args.list_accounts:
            await _list_accounts(
                uow_factory, role=args.role, status=args.status, limit=args.limit, offset=args.offset
            )
            return 0

        if args.disable_account:
            if not args.email and not args.account_id:
                print("error: --disable-account requires --email or --account-id", file=sys.stderr)
                return 2
            await _disable_account(uow_factory, email=args.email, account_id=args.account_id)
            return 0

        if args.revoke_sessions:
            if not args.email and not args.account_id:
                print("error: --revoke-sessions requires --email or --account-id", file=sys.stderr)
                return 2
            await _revoke_sessions(identity_service, uow_factory, email=args.email, account_id=args.account_id)
            return 0

        print(
            "error: specify --create-admin, --list-accounts, --disable-account, or --revoke-sessions",
            file=sys.stderr,
        )
        return 2
    except StockResearchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()

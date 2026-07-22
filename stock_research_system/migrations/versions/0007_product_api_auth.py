"""Product API identity/authentication schema (Phase 9): local
accounts, rotating opaque refresh tokens, and an append-only
authentication/security audit log.

`user_accounts` is a distinct identity concept from `learner_profiles`
(Phase 4) - it references a learner only by an optional, unique foreign
key (`learner_id`), one account per learner in this phase. No column
here is ever returned by a public mapper except `password_hash`, which
is read only through a dedicated infrastructure-internal credential
query used exclusively by authentication code (see
`infrastructure.database.mappers.identity_mappers`).

Revision ID: 0007_product_api_auth
Revises: 0006_grounded_ai_tutor
Create Date: 2026-07-19

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007_product_api_auth"
down_revision: Union[str, None] = "0006_grounded_ai_tutor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- user_accounts -----------------------------------------------
    op.create_table(
        "user_accounts",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("normalized_email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(150), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["learner_id"], ["learner_profiles.learner_id"], name="fk_user_accounts_learner_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("normalized_email", name="uq_user_accounts_normalized_email"),
        sa.UniqueConstraint("learner_id", name="uq_user_accounts_learner_id"),
        sa.CheckConstraint("failed_login_count >= 0", name="ck_user_accounts_failed_login_count_non_negative"),
    )
    op.create_index("ix_user_accounts_role", "user_accounts", ["role"])
    op.create_index("ix_user_accounts_status", "user_accounts", ["status"])

    # -- account_refresh_tokens -----------------------------------------------
    op.create_table(
        "account_refresh_tokens",
        sa.Column("refresh_token_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("issued_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("replaced_by_token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_agent_hash", sa.String(128), nullable=True),
        sa.Column("client_ip_hash", sa.String(128), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["account_id"], ["user_accounts.account_id"], name="fk_account_refresh_tokens_account_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_token_id"], ["account_refresh_tokens.refresh_token_id"],
            name="fk_account_refresh_tokens_replaced_by", ondelete="SET NULL",
        ),
        sa.UniqueConstraint("token_hash", name="uq_account_refresh_tokens_token_hash"),
        sa.CheckConstraint("expires_at > issued_at", name="ck_account_refresh_tokens_expiration_after_issuance"),
    )
    op.create_index("ix_account_refresh_tokens_account_status", "account_refresh_tokens", ["account_id", "status"])
    op.create_index("ix_account_refresh_tokens_token_family_id", "account_refresh_tokens", ["token_family_id"])
    op.create_index("ix_account_refresh_tokens_expires_at", "account_refresh_tokens", ["expires_at"])

    # -- authentication_audit_events (append-only) -----------------------------------------------
    op.create_table(
        "authentication_audit_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("correlation_id", sa.String(200), nullable=False),
        sa.Column("email_hash", sa.String(128), nullable=True),
        sa.Column("client_ip_hash", sa.String(128), nullable=True),
        sa.Column("user_agent_hash", sa.String(128), nullable=True),
        sa.Column("reason_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["account_id"], ["user_accounts.account_id"], name="fk_authentication_audit_events_account_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_authentication_audit_events_account_created", "authentication_audit_events",
        ["account_id", "created_at"],
    )
    op.create_index("ix_authentication_audit_events_event_type", "authentication_audit_events", ["event_type"])
    op.create_index("ix_authentication_audit_events_result", "authentication_audit_events", ["result"])
    op.create_index(
        "ix_authentication_audit_events_correlation_id", "authentication_audit_events", ["correlation_id"]
    )


def downgrade() -> None:
    op.drop_table("authentication_audit_events")
    op.drop_table("account_refresh_tokens")
    op.drop_table("user_accounts")

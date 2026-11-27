"""follow_up_auto_sends — auto-send a saved template when a lead follow-up is due.

follow-up-auto-send Step 1. Creates ``tbl_follow_up_auto_sends`` (one row
per lead follow-up task that should send a template), its two enums, the
sweep's partial index, the per-lead lookup index and the standard
org-isolation RLS policy.

Cascades: task or lead deleted → row deleted; template deleted →
``template_id`` nulled (``template_name`` keeps the label); message
deleted → ``message_id`` nulled.

Downgrade drops the table and both enums.

Revision ID: 0245_follow_up_auto_sends
Revises: 0244_audience_filter_tags
Create Date: 2026-11-27 13:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from src.app.shared.rls import apply_rls, drop_rls

revision: str = "0245_follow_up_auto_sends"
down_revision: str | None = "0244_audience_filter_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "tbl_follow_up_auto_sends"
_STATUSES = ("scheduled", "claimed", "sending", "sent", "failed", "skipped", "cancelled")
_CHANNELS = ("whatsapp", "email")


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_STATUSES, name="follow_up_auto_send_status").create(bind, checkfirst=True)
    postgresql.ENUM(*_CHANNELS, name="follow_up_auto_send_channel").create(bind, checkfirst=True)

    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_tasks.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_message_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("template_name", sa.String(255), nullable=False),
        sa.Column(
            "channel",
            postgresql.ENUM(*_CHANNELS, name="follow_up_auto_send_channel", create_type=False),
            nullable=False,
        ),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*_STATUSES, name="follow_up_auto_send_status", create_type=False),
            nullable=False,
            server_default=sa.text("'scheduled'"),
        ),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cancelled_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(f"ix_{_TABLE}_org_id", _TABLE, ["org_id"])
    op.create_index(f"ix_{_TABLE}_org_lead", _TABLE, ["org_id", "lead_id"])
    op.create_index(
        f"ix_{_TABLE}_pending",
        _TABLE,
        ["status", "not_before"],
        postgresql_where=sa.text("status IN ('scheduled', 'claimed', 'sending')"),
    )
    apply_rls(_TABLE)


def downgrade() -> None:
    drop_rls(_TABLE)
    op.drop_table(_TABLE)
    bind = op.get_bind()
    postgresql.ENUM(name="follow_up_auto_send_channel").drop(bind, checkfirst=True)
    postgresql.ENUM(name="follow_up_auto_send_status").drop(bind, checkfirst=True)

"""Drop WhatsApp Web (unofficial / Baileys) — tasks/whatsapp-web-removal Step 4.

Upgrade, in order:

1. Clear ``tbl_conversations.received_via_phone_id`` where it holds a
   WhatsApp Web session's ``phone_number`` (same org) that is not also a
   Cloud ``phone_id`` in that org. The send path resolves the Cloud
   config by that value, so a Web number made those threads
   unanswerable; NULL routes replies through the org's default Cloud
   number. Must run before step 2 — the sessions table is the only
   lookup that identifies them.
2. Drop ``tbl_whatsapp_web_sessions`` (policy, partial index, table).
3. Delete ``whatsapp_web`` rows from ``tbl_integration_dlq`` (its FK is
   ``ON DELETE SET NULL``, so the rows would outlive their integration
   with the enum value still set).
4. Delete ``whatsapp_web`` rows from ``tbl_integrations``.
5. Forbid the value with CHECK constraints on both enum-typed columns.
   The ``whatsapp_web`` label stays in the ``integration_provider``
   Postgres enum: dropping one label means recreating the type and
   rewriting live tables (same call as 0141's downgrade).

Downgrade drops the CHECKs and recreates the empty sessions table
exactly as 0141 created it. Deleted rows and cleared
``received_via_phone_id`` values are not restored.

Revision ID: 0243_drop_whatsapp_web
Revises:     0242_conv_snooze_saved_replies
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0243_drop_whatsapp_web"
down_revision: str | None = "0242_conv_snooze_saved_replies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SESSIONS = "tbl_whatsapp_web_sessions"
_POLICY = "tbl_whatsapp_web_sessions_tenant_isolation"
_INDEX = "ix_whatsapp_web_sessions_active"
_CHECKS = (
    ("tbl_integrations", "ck_integrations_provider_not_whatsapp_web"),
    ("tbl_integration_dlq", "ck_integration_dlq_provider_not_whatsapp_web"),
)
_STATUS_VALUES = (
    "pending",
    "pairing",
    "connected",
    "reconnecting",
    "disconnected",
    "logged_out",
    "error",
)


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE tbl_conversations AS c
           SET received_via_phone_id = NULL
          FROM {_SESSIONS} AS s
         WHERE s.org_id = c.org_id
           AND s.phone_number IS NOT NULL
           AND c.received_via_phone_id = s.phone_number
           AND NOT EXISTS (
                 SELECT 1
                   FROM tbl_whatsapp_account_configs AS w
                  WHERE w.org_id = c.org_id
                    AND w.phone_id = c.received_via_phone_id
               )
        """
    )

    op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON {_SESSIONS}")
    op.drop_index(_INDEX, table_name=_SESSIONS)
    op.drop_table(_SESSIONS)

    op.execute("DELETE FROM tbl_integration_dlq WHERE provider = 'whatsapp_web'")
    op.execute("DELETE FROM tbl_integrations WHERE provider = 'whatsapp_web'")

    for table, name in _CHECKS:
        op.create_check_constraint(name, table, "provider <> 'whatsapp_web'")


def downgrade() -> None:
    for table, name in _CHECKS:
        op.drop_constraint(name, table, type_="check")

    status_check = "status IN (" + ", ".join(f"'{v}'" for v in _STATUS_VALUES) + ")"
    op.create_table(
        _SESSIONS,
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
            index=True,
        ),
        sa.Column(
            "integration_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sidecar_session_id", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("phone_number", sa.Text(), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.CheckConstraint(status_check, name="ck_whatsapp_web_sessions_status"),
        sa.UniqueConstraint("integration_id", name="uq_whatsapp_web_sessions_integration_id"),
        sa.UniqueConstraint(
            "sidecar_session_id", name="uq_whatsapp_web_sessions_sidecar_session_id"
        ),
    )
    op.create_index(
        _INDEX,
        _SESSIONS,
        ["org_id", "integration_id"],
        postgresql_where=sa.text("status NOT IN ('disconnected', 'logged_out')"),
    )
    op.execute(f"ALTER TABLE {_SESSIONS} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {_POLICY}
            ON {_SESSIONS}
            USING (
                org_id::text = current_setting('app.current_org_id', true)
            )
            WITH CHECK (
                org_id::text = current_setting('app.current_org_id', true)
            )
        """
    )

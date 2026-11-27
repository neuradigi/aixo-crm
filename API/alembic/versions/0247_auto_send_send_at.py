"""auto_send_send_at — let a follow-up's auto-message go at its own time.

follow-up-auto-send Step 10. Adds nullable ``tbl_follow_up_auto_sends.send_at``.
NULL (every existing row) keeps today's behaviour: the message goes at
the follow-up's live due time and moves when the follow-up is
rescheduled. A value is a fixed send time picked in the Update Status
modal.

Downgrade drops the column; rows that had a custom time then send at
their follow-up's due time.

Revision ID: 0247_auto_send_send_at
Revises: 0246_task_due_reminder
Create Date: 2026-11-27 19:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0247_auto_send_send_at"
down_revision: str | None = "0246_task_due_reminder"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_follow_up_auto_sends",
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_follow_up_auto_sends", "send_at")

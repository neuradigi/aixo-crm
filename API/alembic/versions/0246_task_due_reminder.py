"""task_due_reminder — remember when a follow-up's "due now" bell was sent.

follow-up-auto-send Step 7. Adds nullable ``tbl_tasks.due_reminder_sent_at``.
The reminder sweep stamps it when it sends the bell, so each due time is
reminded once; ``update_task`` clears it when ``due_at`` changes.
Existing rows stay NULL — the sweep only looks at follow-ups due in the
last hour, so old open tasks are never reminded in bulk.

Downgrade drops the column.

Revision ID: 0246_task_due_reminder
Revises: 0245_follow_up_auto_sends
Create Date: 2026-11-27 14:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0246_task_due_reminder"
down_revision: str | None = "0245_follow_up_auto_sends"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_tasks",
        sa.Column("due_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_tasks", "due_reminder_sent_at")

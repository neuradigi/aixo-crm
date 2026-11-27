"""Data-access layer for follow-up auto-sends.

Pure query helpers — no transactions, no business rules. Leaf module;
never imports a service or router.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, case, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.leads.auto_send.models import (
    PENDING_STATUSES,
    FollowUpAutoSend,
    FollowUpAutoSendStatus,
)
from src.app.core.leads.models import Lead
from src.app.core.tasks.models import Task, TaskStatus

# Statuses a cancel may move from. `sending` is excluded: the provider
# call is already under way.
_CANCELLABLE = (FollowUpAutoSendStatus.scheduled, FollowUpAutoSendStatus.claimed)


def insert_auto_send(session: AsyncSession, row: FollowUpAutoSend) -> FollowUpAutoSend:
    """Stage a new row in the caller's transaction."""
    session.add(row)
    return row


async def get_auto_send_for_task(
    session: AsyncSession, *, org_id: uuid.UUID, task_id: uuid.UUID
) -> FollowUpAutoSend | None:
    result = await session.execute(
        select(FollowUpAutoSend).where(
            FollowUpAutoSend.org_id == org_id, FollowUpAutoSend.task_id == task_id
        )
    )
    return result.scalar_one_or_none()


async def list_pending_auto_sends_for_contact(
    session: AsyncSession, *, org_id: uuid.UUID, contact_id: uuid.UUID
) -> list[tuple[FollowUpAutoSend, datetime | None]]:
    """Pending rows (scheduled / claimed / sending) on any of the contact's
    leads, each with its task's live ``due_at`` — the "one pending
    auto-send per person" check and the modal's banner read this."""
    result = await session.execute(
        select(FollowUpAutoSend, Task.due_at)
        .join(Lead, Lead.id == FollowUpAutoSend.lead_id)
        .join(Task, Task.id == FollowUpAutoSend.task_id)
        .where(
            FollowUpAutoSend.org_id == org_id,
            Lead.contact_id == contact_id,
            FollowUpAutoSend.status.in_(PENDING_STATUSES),
        )
        .order_by(FollowUpAutoSend.created_at)
    )
    return [(row, due_at) for row, due_at in result.all()]


async def cancel_pending_auto_sends(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    ids: list[uuid.UUID],
    cancelled_by_id: uuid.UUID,
    reason: str,
    now: datetime,
) -> list[uuid.UUID]:
    """Compare-and-set ``scheduled | claimed → cancelled``. Returns the ids
    actually cancelled; a row a sweep has moved to ``sending`` meanwhile
    is left alone and missing from the result."""
    if not ids:
        return []
    result = await session.execute(
        update(FollowUpAutoSend)
        .where(
            FollowUpAutoSend.org_id == org_id,
            FollowUpAutoSend.id.in_(ids),
            FollowUpAutoSend.status.in_(_CANCELLABLE),
        )
        .values(
            status=FollowUpAutoSendStatus.cancelled,
            reason=reason,
            cancelled_by_id=cancelled_by_id,
            cancelled_at=now,
            claim_token=None,
        )
        .returning(FollowUpAutoSend.id)
    )
    return list(result.scalars().all())


async def get_auto_send(
    session: AsyncSession, *, org_id: uuid.UUID, auto_send_id: uuid.UUID
) -> tuple[FollowUpAutoSend, Task] | None:
    """The row and its task (fresh from the DB), or None."""
    result = await session.execute(
        select(FollowUpAutoSend, Task)
        .join(Task, Task.id == FollowUpAutoSend.task_id)
        .where(FollowUpAutoSend.org_id == org_id, FollowUpAutoSend.id == auto_send_id)
        .execution_options(populate_existing=True)
    )
    row = result.first()
    return (row[0], row[1]) if row else None


async def list_auto_sends_for_tasks(
    session: AsyncSession, *, org_id: uuid.UUID, task_ids: list[uuid.UUID]
) -> list[tuple[FollowUpAutoSend, datetime | None]]:
    """Every auto-send attached to ``task_ids`` (at most one per task),
    with the task's live ``due_at`` — one query for a whole list page."""
    if not task_ids:
        return []
    result = await session.execute(
        select(FollowUpAutoSend, Task.due_at)
        .join(Task, Task.id == FollowUpAutoSend.task_id)
        .where(FollowUpAutoSend.org_id == org_id, FollowUpAutoSend.task_id.in_(task_ids))
    )
    return [(row, due_at) for row, due_at in result.all()]


async def cancel_scheduled_for_dead_tasks(session: AsyncSession, *, now: datetime) -> int:
    """Housekeeping, across every org: cancel ``scheduled`` auto-sends
    whose follow-up is no longer open, has no due time, or changed to a
    type that doesn't match the channel. Catches every writer of
    ``tbl_tasks`` (bulk complete, the nightly groom's raw UPDATE, …)
    without hooks in each. Returns how many rows were cancelled."""
    channel_matches = cast(Task.followup_type, String) == cast(FollowUpAutoSend.channel, String)
    reason = case(
        (Task.status != TaskStatus.open, "follow_up_closed"),
        (Task.due_at.is_(None), "follow_up_undated"),
        else_="follow_up_retyped",
    )
    result = await session.execute(
        update(FollowUpAutoSend)
        .where(
            Task.id == FollowUpAutoSend.task_id,
            FollowUpAutoSend.status == FollowUpAutoSendStatus.scheduled,
            or_(
                Task.status != TaskStatus.open,
                Task.due_at.is_(None),
                Task.followup_type.is_(None),
                ~channel_matches,
            ),
        )
        .values(
            status=FollowUpAutoSendStatus.cancelled,
            reason=reason,
            cancelled_at=now,
            claim_token=None,
        )
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


async def count_auto_sends_created_by(
    session: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID, since: datetime
) -> int:
    """How many auto-sends ``user_id`` scheduled since ``since``."""
    result = await session.execute(
        select(func.count())
        .select_from(FollowUpAutoSend)
        .where(
            FollowUpAutoSend.org_id == org_id,
            FollowUpAutoSend.created_by_id == user_id,
            FollowUpAutoSend.created_at >= since,
        )
    )
    return int(result.scalar_one())

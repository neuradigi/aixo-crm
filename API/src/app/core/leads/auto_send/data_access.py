"""Data-access layer for follow-up auto-sends.

Pure query helpers — no transactions, no business rules. Leaf module;
never imports a service or router.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.leads.auto_send.models import PENDING_STATUSES, FollowUpAutoSend
from src.app.core.leads.models import Lead


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
) -> list[FollowUpAutoSend]:
    """Pending rows (scheduled / claimed / sending) on any of the contact's
    leads — the "one pending auto-send per person" check reads this."""
    result = await session.execute(
        select(FollowUpAutoSend)
        .join(Lead, Lead.id == FollowUpAutoSend.lead_id)
        .where(
            FollowUpAutoSend.org_id == org_id,
            Lead.contact_id == contact_id,
            FollowUpAutoSend.status.in_(PENDING_STATUSES),
        )
        .order_by(FollowUpAutoSend.created_at)
    )
    return list(result.scalars().all())

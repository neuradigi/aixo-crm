"""Follow-up auto-send business rules.

Scheduling happens inside the Update Status (log-update) transaction:
:func:`stage_auto_send` checks every rule, holds the contact's row lock
while it enforces "one pending auto-send per person", inserts the row
and its timeline entry, and never commits. The caller commits, then
calls :func:`publish_auto_send_staged` for audit + notifications.

Every refusal is an HTTP error whose ``detail`` carries a fixed
``error`` code and a ``message`` the modal shows under the field.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.activities import service as activities_service
from src.app.core.activities.models import ActivityType
from src.app.core.automation.send_guard import check_dpdp_suppression
from src.app.core.contacts import data_access as contacts_da
from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppNotConnected,
    resolve_whatsapp_adapter,
)
from src.app.core.conversations.template_send_service import (
    contact_address,
    template_unavailable_reason,
)
from src.app.core.email import data_access as email_da
from src.app.core.email_sender_setup.service import (
    SendNotConfiguredError,
    resolve_send_envelope,
)
from src.app.core.integrations.whatsapp.block_list import is_blocked
from src.app.core.leads.auto_send import data_access as auto_send_da
from src.app.core.leads.auto_send.models import (
    FollowUpAutoSend,
    FollowUpAutoSendChannel,
    FollowUpAutoSendStatus,
)
from src.app.core.leads.auto_send.schemas import AutoSendSummary
from src.app.core.leads.models import Lead
from src.app.core.notifications.service import notify
from src.app.core.tasks.models import Task, TaskFollowupType
from src.app.core.templates import data_access as templates_da
from src.app.core.workflows.compliance import falls_in_quiet_hours

# A follow-up time a few minutes in the past is still "now" (form fill time).
AUTO_SEND_PAST_GRACE = timedelta(minutes=5)
AUTO_SEND_HORIZON = timedelta(days=90)
AUTO_SEND_DAILY_CAP_PER_USER = 100

_CHANNEL_BY_FOLLOWUP_TYPE = {
    TaskFollowupType.whatsapp: FollowUpAutoSendChannel.whatsapp,
    TaskFollowupType.email: FollowUpAutoSendChannel.email,
}


def _reject(status_code: int, error: str, message: str, **extra: object) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": error, "message": message, **extra}
    )


def summarize(row: FollowUpAutoSend, due_at: datetime | None) -> AutoSendSummary:
    return AutoSendSummary(
        id=row.id,
        task_id=row.task_id,
        lead_id=row.lead_id,
        status=row.status,
        channel=row.channel,
        template_name=row.template_name,
        due_at=due_at,
        reason=row.reason,
        created_by_id=row.created_by_id,
    )


@dataclass(frozen=True)
class StagedAutoSend:
    row: FollowUpAutoSend
    due_at: datetime
    contact_name: str
    # Pending rows of the same person cancelled because of `replace`.
    replaced: list[FollowUpAutoSend]


async def stage_auto_send(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    lead: Lead,
    task: Task,
    template_id: uuid.UUID,
    actor_id: uuid.UUID,
    lead_closing: bool,
    replace: bool,
) -> StagedAutoSend:
    """Validate and stage an auto-send for ``task`` (a freshly inserted
    lead follow-up). Flushes, never commits."""
    channel = _CHANNEL_BY_FOLLOWUP_TYPE.get(task.followup_type) if task.followup_type else None
    if channel is None:
        raise _reject(
            422, "auto_send_type", "Auto-messages are available for WhatsApp and Email follow-ups."
        )

    template = await templates_da.get_template(session, org_id=org_id, template_id=template_id)
    unavailable = template_unavailable_reason(template)
    if unavailable is not None or template is None:
        raise _reject(
            422,
            "auto_send_template_unavailable",
            "This template can't be auto-sent — it must be published, active and, for "
            "WhatsApp, approved by Meta.",
            reason=unavailable or "template_unavailable",
        )
    if template.channel.value != channel.value:
        raise _reject(
            422, "auto_send_template_channel", "Pick a template for the follow-up's channel."
        )
    if lead_closing:
        raise _reject(
            422, "auto_send_lead_closed", "Auto-messages can't be scheduled on a Won or Lost lead."
        )

    now = datetime.now(UTC)
    due_at = task.due_at if task.due_at.tzinfo else task.due_at.replace(tzinfo=UTC)
    if due_at < now - AUTO_SEND_PAST_GRACE:
        raise _reject(422, "auto_send_past_due", "Pick a follow-up time in the future.")
    if due_at > now + AUTO_SEND_HORIZON:
        raise _reject(
            422,
            "auto_send_too_far",
            f"Auto-messages can be scheduled up to {AUTO_SEND_HORIZON.days} days ahead.",
        )

    # Lock the person first: two staff scheduling for the same contact
    # serialise here, so the one-pending check below is exact.
    locked = await contacts_da.lock_contacts(session, org_id=org_id, contact_ids=[lead.contact_id])
    contact = locked[0] if locked else None
    if contact is None or contact.anonymised_at is not None:
        raise _reject(
            422, "auto_send_contact_unavailable", "This contact can no longer be messaged."
        )
    address = contact_address(contact, template.channel)
    if address is None:
        missing = "phone number" if channel == FollowUpAutoSendChannel.whatsapp else "email address"
        raise _reject(422, "auto_send_no_address", f"Add a {missing} to the contact first.")
    if not check_dpdp_suppression(channel=channel.value, contact=contact).allow:
        raise _reject(422, "auto_send_opted_out", "This contact has opted out of this channel.")

    if channel == FollowUpAutoSendChannel.whatsapp:
        if await is_blocked(session, org_id=org_id, phone=address) is not None:
            raise _reject(422, "auto_send_blocked", "This number is on the WhatsApp block list.")
        try:
            await resolve_whatsapp_adapter(session)
        except WhatsAppNotConnected as exc:
            raise _reject(
                422, "auto_send_channel_not_connected", "Connect WhatsApp before scheduling."
            ) from exc
    elif (
        await email_da.find_live_account_for_user(
            session, org_id=org_id, user_id=task.assigned_to_id
        )
        is None
    ):
        try:
            await resolve_send_envelope(session, org_id=org_id)
        except SendNotConfiguredError as exc:
            raise _reject(
                422,
                "auto_send_channel_not_connected",
                "Connect a mailbox or set up an email sender before scheduling.",
            ) from exc

    if await falls_in_quiet_hours(
        session, org_id=org_id, at=due_at, category=template.category.value
    ):
        raise _reject(
            422,
            "auto_send_quiet_hours",
            "That time is inside your quiet hours — pick a time outside them.",
        )

    sent_today = await auto_send_da.count_auto_sends_created_by(
        session, org_id=org_id, user_id=actor_id, since=now - timedelta(days=1)
    )
    if sent_today >= AUTO_SEND_DAILY_CAP_PER_USER:
        raise _reject(
            422,
            "auto_send_daily_limit",
            f"You can schedule up to {AUTO_SEND_DAILY_CAP_PER_USER} auto-messages a day.",
        )

    pending = await auto_send_da.list_pending_auto_sends_for_contact(
        session, org_id=org_id, contact_id=contact.id
    )
    replaced: list[FollowUpAutoSend] = []
    if pending:
        existing_row, existing_due = pending[0]
        if not replace:
            raise _reject(
                409,
                "auto_send_exists",
                "This person already has an auto-message scheduled.",
                existing=summarize(existing_row, existing_due).model_dump(mode="json"),
            )
        ids = [row.id for row, _ in pending]
        cancelled = await auto_send_da.cancel_pending_auto_sends(
            session,
            org_id=org_id,
            ids=ids,
            cancelled_by_id=actor_id,
            reason="replaced",
            now=now,
        )
        if len(cancelled) != len(ids):
            raise _reject(
                409,
                "auto_send_sending",
                "The scheduled auto-message is being sent right now — try again in a minute.",
            )
        replaced = [row for row, _ in pending]

    row = auto_send_da.insert_auto_send(
        session,
        FollowUpAutoSend(
            org_id=org_id,
            task_id=task.id,
            lead_id=lead.id,
            template_id=template.id,
            template_name=template.name,
            channel=channel,
            recipient=address,
            created_by_id=actor_id,
        ),
    )
    await session.flush()

    for old in replaced:
        await activities_service.record_in_session(
            session,
            org_id=org_id,
            entity_type="lead",
            entity_id=old.lead_id,
            type=ActivityType.task,
            payload={
                "text": f"Scheduled auto-message “{old.template_name}” replaced",
                "auto_send_id": str(old.id),
                "status": FollowUpAutoSendStatus.cancelled.value,
            },
            user_id=actor_id,
        )
    await activities_service.record_in_session(
        session,
        org_id=org_id,
        entity_type="lead",
        entity_id=lead.id,
        type=ActivityType.task,
        payload={
            "text": f"Auto-message scheduled: “{template.name}” by {channel.value}",
            "auto_send_id": str(row.id),
            "status": FollowUpAutoSendStatus.scheduled.value,
            "due_at": due_at.isoformat(),
        },
        user_id=actor_id,
    )
    return StagedAutoSend(row=row, due_at=due_at, contact_name=contact.full_name, replaced=replaced)


async def publish_auto_send_staged(
    staged: StagedAutoSend, *, org_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    """After the caller's commit: audit the schedule (and any rows it
    replaced) and tell each replaced row's creator."""
    row = staged.row
    await audit.log(
        "leads.auto_send_scheduled",
        entity_type="follow_up_auto_send",
        entity_id=row.id,
        after={
            "task_id": str(row.task_id),
            "lead_id": str(row.lead_id),
            "template_id": str(row.template_id),
            "channel": row.channel.value,
            "due_at": staged.due_at.isoformat(),
        },
    )
    for old in staged.replaced:
        await audit.log(
            "leads.auto_send_cancelled",
            entity_type="follow_up_auto_send",
            entity_id=old.id,
            after={"reason": "replaced", "replaced_by": str(row.id)},
        )
        if old.created_by_id != actor_id:
            await notify(
                org_id=org_id,
                user_id=old.created_by_id,
                type="follow_up.auto_send_cancelled",
                title="Your scheduled auto-message was replaced",
                body=(
                    f"“{old.template_name}” to {staged.contact_name} was replaced by a "
                    "colleague's new auto-message."
                ),
                payload={"lead_id": str(old.lead_id), "auto_send_id": str(old.id)},
            )


async def get_pending_auto_send(
    session: AsyncSession, *, org_id: uuid.UUID, contact_id: uuid.UUID
) -> AutoSendSummary | None:
    """The person's pending auto-send (on any of their leads), if any."""
    pending = await auto_send_da.list_pending_auto_sends_for_contact(
        session, org_id=org_id, contact_id=contact_id
    )
    if not pending:
        return None
    row, due_at = pending[0]
    return summarize(row, due_at)


async def summaries_for_tasks(
    session: AsyncSession, *, org_id: uuid.UUID, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, AutoSendSummary]:
    """Auto-send summary per task id for a list page — one query."""
    rows = await auto_send_da.list_auto_sends_for_tasks(session, org_id=org_id, task_ids=task_ids)
    return {row.task_id: summarize(row, due_at) for row, due_at in rows}


async def cancel_auto_send(
    session: AsyncSession, *, org_id: uuid.UUID, auto_send_id: uuid.UUID, actor_id: uuid.UUID
) -> AutoSendSummary:
    """Cancel a scheduled (or claimed, not yet sending) auto-send. 404 for
    another org's id, 409 while it is being sent or once it is final.
    Commits; then audits and tells the creator and the follow-up's
    assignee (whoever isn't the actor)."""
    found = await auto_send_da.get_auto_send(session, org_id=org_id, auto_send_id=auto_send_id)
    if found is None:
        raise HTTPException(status_code=404, detail="auto-send not found")
    row, task = found
    if row.status == FollowUpAutoSendStatus.sending:
        raise _reject(409, "auto_send_sending", "This auto-message is being sent right now.")
    cancelled = await auto_send_da.cancel_pending_auto_sends(
        session,
        org_id=org_id,
        ids=[row.id],
        cancelled_by_id=actor_id,
        reason="cancelled_by_user",
        now=datetime.now(UTC),
    )
    if not cancelled:
        raise _reject(409, "auto_send_not_pending", "This auto-message is no longer scheduled.")
    await activities_service.record_in_session(
        session,
        org_id=org_id,
        entity_type="lead",
        entity_id=row.lead_id,
        type=ActivityType.task,
        payload={
            "text": f"Scheduled auto-message “{row.template_name}” cancelled",
            "auto_send_id": str(row.id),
            "status": FollowUpAutoSendStatus.cancelled.value,
        },
        user_id=actor_id,
    )
    await session.commit()

    refreshed = await auto_send_da.get_auto_send(session, org_id=org_id, auto_send_id=row.id)
    row, task = refreshed if refreshed is not None else (row, task)
    await audit.log(
        "leads.auto_send_cancelled",
        entity_type="follow_up_auto_send",
        entity_id=row.id,
        after={"reason": "cancelled_by_user"},
    )
    for recipient in {row.created_by_id, task.assigned_to_id} - {actor_id}:
        await notify(
            org_id=org_id,
            user_id=recipient,
            type="follow_up.auto_send_cancelled",
            title="A scheduled auto-message was cancelled",
            body=f"“{row.template_name}” on a follow-up was cancelled by a colleague.",
            payload={"lead_id": str(row.lead_id), "auto_send_id": str(row.id)},
        )
    return summarize(row, task.due_at)


async def guard_reschedule(
    session: AsyncSession, *, org_id: uuid.UUID, task_id: uuid.UUID, new_due_at: datetime | None
) -> None:
    """Refuse moving a follow-up that has a scheduled auto-message to a
    time the message couldn't go out at. Called by the tasks service
    before it writes a new ``due_at``; a task without a pending
    auto-send is never blocked."""
    row = await auto_send_da.get_auto_send_for_task(session, org_id=org_id, task_id=task_id)
    if row is None or row.status not in (
        FollowUpAutoSendStatus.scheduled,
        FollowUpAutoSendStatus.claimed,
    ):
        return
    if new_due_at is None:
        raise _reject(
            422,
            "auto_send_due_required",
            "This follow-up has an auto-message scheduled — cancel it before clearing the date.",
        )
    due_at = new_due_at if new_due_at.tzinfo else new_due_at.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    if due_at < now - AUTO_SEND_PAST_GRACE:
        raise _reject(
            422,
            "auto_send_past_due",
            "This follow-up has an auto-message scheduled — pick a future time or cancel it.",
        )
    if due_at > now + AUTO_SEND_HORIZON:
        raise _reject(
            422,
            "auto_send_too_far",
            f"Auto-messages can be scheduled up to {AUTO_SEND_HORIZON.days} days ahead.",
        )
    template = (
        await templates_da.get_template(session, org_id=org_id, template_id=row.template_id)
        if row.template_id
        else None
    )
    if template is not None and await falls_in_quiet_hours(
        session, org_id=org_id, at=due_at, category=template.category.value
    ):
        raise _reject(
            422,
            "auto_send_quiet_hours",
            "That time is inside your quiet hours — pick a time outside them.",
        )


async def housekeep(session: AsyncSession) -> int:
    """Cancel scheduled auto-sends whose follow-up was closed, undated or
    changed type, across every org. Commits. Run by the sweep."""
    cancelled = await auto_send_da.cancel_scheduled_for_dead_tasks(session, now=datetime.now(UTC))
    await session.commit()
    return cancelled


async def cancel_on_reply(
    session: AsyncSession, *, org_id: uuid.UUID, contact_id: uuid.UUID
) -> int:
    """The contact messaged us: cancel their scheduled (or claimed, not yet
    sending) auto-sends — the conversation has moved on since the
    follow-up was set. Writes a timeline entry, commits, then tells the
    follow-up's assignee and whoever scheduled it. Returns how many were
    cancelled."""
    pending = await auto_send_da.list_pending_auto_sends_for_contact(
        session, org_id=org_id, contact_id=contact_id
    )
    ids = [
        row.id
        for row, _ in pending
        if row.status in (FollowUpAutoSendStatus.scheduled, FollowUpAutoSendStatus.claimed)
    ]
    cancelled_ids = set(
        await auto_send_da.cancel_pending_auto_sends(
            session,
            org_id=org_id,
            ids=ids,
            cancelled_by_id=None,
            reason="lead_replied",
            now=datetime.now(UTC),
        )
    )
    if not cancelled_ids:
        return 0

    cancelled: list[tuple[FollowUpAutoSend, Task]] = []
    for row_id in cancelled_ids:
        found = await auto_send_da.get_auto_send(session, org_id=org_id, auto_send_id=row_id)
        if found is not None:
            cancelled.append(found)
    for row, _task in cancelled:
        await activities_service.record_in_session(
            session,
            org_id=org_id,
            entity_type="lead",
            entity_id=row.lead_id,
            type=ActivityType.task,
            payload={
                "text": f"Scheduled auto-message “{row.template_name}” cancelled — the lead replied",
                "auto_send_id": str(row.id),
                "status": FollowUpAutoSendStatus.cancelled.value,
                "reason": "lead_replied",
            },
        )
    await session.commit()

    for row, task in cancelled:
        await audit.log(
            "leads.auto_send_cancelled",
            entity_type="follow_up_auto_send",
            entity_id=row.id,
            after={"reason": "lead_replied"},
        )
        for user_id in {task.assigned_to_id, row.created_by_id}:
            await notify(
                org_id=org_id,
                user_id=user_id,
                type="follow_up.auto_send_cancelled",
                title="Auto-message cancelled — the lead replied",
                body=(
                    f"“{row.template_name}” was not sent because the lead messaged you first. "
                    "Check the conversation."
                ),
                payload={"lead_id": str(row.lead_id), "auto_send_id": str(row.id)},
            )
    return len(cancelled)

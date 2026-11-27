"""The follow-up auto-send sweep — sends due auto-messages exactly once.

Runs every minute (``leads/auto_send/tasks.py``). One pass:

1. **Housekeeping** — cancel scheduled rows whose follow-up was closed,
   undated or retyped.
2. **Reaper** — ``claimed`` rows never started → back to ``scheduled``;
   ``sending`` rows whose outcome is unknown → ``sent`` if a message
   carries their id, else ``failed / interrupted`` (never resent).
3. **Claim rounds** until nothing is due or the time budget is spent:
   oldest due first, at most :data:`CLAIMS_PER_ORG` per org per round so
   one org's backlog can't starve the rest.
4. **Per row** — own session with the row's org as request context;
   re-check everything at send time; ``claimed → sending`` (compare-and-
   set on the claim token) → :func:`send_template_to_contact` → record
   the outcome (compare-and-set again). A cancel or reschedule that lands
   between claim and send wins: the transition no longer applies.

At-most-once: an uncertain outcome is never retried; only a definite
WhatsApp 429 is (back to ``scheduled`` after a back-off, max
:data:`MAX_ATTEMPTS`).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.activities import service as activities_service
from src.app.core.activities.models import ActivityType
from src.app.core.contacts import service as contacts_service
from src.app.core.conversations.models import ConversationChannel
from src.app.core.conversations.template_send_service import (
    SendOutcome,
    contact_address,
    send_template_to_contact,
)
from src.app.core.leads.auto_send import data_access as auto_send_da
from src.app.core.leads.auto_send.models import FollowUpAutoSend, FollowUpAutoSendStatus
from src.app.core.leads.auto_send.service import housekeep, send_time
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.notifications.service import notify
from src.app.core.permissions.service import role_has_permission
from src.app.core.subscriptions.entitlements import load_for_org
from src.app.core.tasks import service as tasks_service
from src.app.core.tasks.models import Task, TaskStatus
from src.app.core.tasks.schemas import TaskUpdate
from src.app.core.templates import data_access as templates_da
from src.app.core.users import service as users_service
from src.app.core.workflows.compliance import falls_in_quiet_hours
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session

log = logging.getLogger(__name__)

SWEEP_BUDGET_SECONDS = 45
CLAIM_BATCH = 200
CLAIMS_PER_ORG = 25
STALE_CLAIM_AFTER = timedelta(minutes=5)
STALE_SENDING_AFTER = timedelta(minutes=15)
MAX_LATENESS = timedelta(hours=6)
RETRY_BACKOFF = timedelta(minutes=5)
MAX_ATTEMPTS = 3
_REAP_BATCH = 100

# Plain-language "why it wasn't sent", for the timeline and the bell.
REASON_TEXT = {
    "too_late": "it was more than 6 hours late",
    "lead_closed": "the lead is Won or Lost",
    "template_unavailable": "the template is no longer available",
    "template_not_approved": "the template is not approved by Meta",
    "template_wrong_channel": "the template no longer matches the channel",
    "template_variables_missing": "the template's variables could not be filled",
    "contact_missing": "the contact no longer exists",
    "contact_anonymised": "the contact was anonymised",
    "recipient_changed": "the contact's phone or email changed after it was scheduled",
    "org_read_only": "your subscription is not active",
    "sender_unavailable": "the assigned person can no longer send messages",
    "quiet_hours": "it fell inside your quiet hours",
    "opted_out": "the contact has opted out",
    "blocked": "the number is on the block list",
    "no_phone": "the contact has no phone number",
    "no_email": "the contact has no email address",
    "whatsapp_not_connected": "WhatsApp is not connected",
    "provider_rejected": "WhatsApp refused it",
    "rate_limited": "WhatsApp kept rate-limiting it",
    "render_failed": "the email could not be filled in",
    "mailbox_daily_cap": "the mailbox reached its daily sending limit",
    "missing_company_address": "your company address is missing (required for email)",
    "interrupted": "it was interrupted — it may or may not have gone out",
}


def reason_text(code: str | None) -> str:
    return REASON_TEXT.get(code or "", "it could not be sent")


@dataclass
class SweepResult:
    housekept: int = 0
    released: int = 0
    reaped: int = 0
    outcomes: Counter = field(default_factory=Counter)


def pick_fairly(
    candidates: list[tuple[uuid.UUID, uuid.UUID]], *, per_org: int, limit: int
) -> list[uuid.UUID]:
    """From ``(id, org_id)`` candidates (oldest due first), take at most
    ``per_org`` per org and ``limit`` overall, keeping due order."""
    taken: Counter = Counter()
    chosen: list[uuid.UUID] = []
    for row_id, org_id in candidates:
        if taken[org_id] >= per_org:
            continue
        taken[org_id] += 1
        chosen.append(row_id)
        if len(chosen) >= limit:
            break
    return chosen


async def run_sweep(*, budget_seconds: float = SWEEP_BUDGET_SECONDS) -> SweepResult:
    """One beat tick. Never raises for a single row's failure."""
    result = SweepResult()
    async with async_session() as session:
        result.housekept = await housekeep(session)
    await _reap(result)

    deadline = time.monotonic() + budget_seconds
    while time.monotonic() < deadline:
        claims = await _claim_round()
        if not claims:
            break
        for index, (auto_send_id, org_id, token) in enumerate(claims):
            if time.monotonic() >= deadline:
                # Out of budget: hand the rest straight back instead of
                # leaving them for the reaper.
                await _release_unstarted(claims[index:])
                return result
            result.outcomes[await _process(auto_send_id, org_id, token)] += 1
    return result


async def _claim_round() -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
    now = datetime.now(UTC)
    token = uuid.uuid4()
    async with async_session() as session:
        candidates = await auto_send_da.select_due_candidates(
            session, now=now, limit=CLAIM_BATCH * 4
        )
        chosen = pick_fairly(candidates, per_org=CLAIMS_PER_ORG, limit=CLAIM_BATCH)
        claimed = await auto_send_da.mark_claimed(session, ids=chosen, claim_token=token, now=now)
        await session.commit()
    return [(row_id, org_id, token) for row_id, org_id in claimed]


async def _release_unstarted(claims: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]) -> None:
    async with async_session() as session:
        for auto_send_id, _org_id, token in claims:
            await auto_send_da.transition(
                session,
                auto_send_id=auto_send_id,
                claim_token=token,
                from_status=FollowUpAutoSendStatus.claimed,
                values={
                    "status": FollowUpAutoSendStatus.scheduled,
                    "claim_token": None,
                    "claimed_at": None,
                },
            )
        await session.commit()


@dataclass(frozen=True)
class _Verdict:
    action: str  # "send" | "release" | "cancel" | "skip"
    code: str | None = None


async def _send_time_verdict(
    session: AsyncSession, *, row: FollowUpAutoSend, task: Task, lead: Lead, now: datetime
) -> _Verdict:
    """Everything that may have changed since scheduling."""
    if task.status != TaskStatus.open:
        return _Verdict("cancel", "follow_up_closed")
    if task.due_at is None:
        return _Verdict("cancel", "follow_up_undated")
    if task.followup_type is None or task.followup_type.value != row.channel.value:
        return _Verdict("cancel", "follow_up_retyped")
    when = send_time(row, task.due_at)
    due_at = when if when.tzinfo else when.replace(tzinfo=UTC)
    if due_at > now:
        return _Verdict("release")  # rescheduled later after the claim
    if now - due_at > MAX_LATENESS:
        return _Verdict("skip", "too_late")
    if lead.status != LeadStatus.active:
        return _Verdict("skip", "lead_closed")
    if row.template_id is None:
        return _Verdict("skip", "template_unavailable")

    contact = await contacts_service.get_contact(session, lead.contact_id)
    if contact is None:
        return _Verdict("skip", "contact_missing")
    if contact.anonymised_at is not None:
        return _Verdict("skip", "contact_anonymised")
    if contact_address(contact, ConversationChannel(row.channel.value)) != row.recipient:
        return _Verdict("skip", "recipient_changed")

    if (await load_for_org(session, row.org_id)).is_read_only:
        return _Verdict("skip", "org_read_only")

    sender = await users_service.get_user_by_uuid(session, task.assigned_to_id)
    membership = sender.active_membership if sender is not None else None
    if (
        membership is None
        or membership.organization_id != row.org_id
        or not await role_has_permission(session, membership.role_id, "conversations.write")
    ):
        return _Verdict("skip", "sender_unavailable")

    template = await templates_da.get_template(
        session, org_id=row.org_id, template_id=row.template_id
    )
    if template is not None and await falls_in_quiet_hours(
        session, org_id=row.org_id, at=now, category=template.category.value
    ):
        return _Verdict("skip", "quiet_hours")
    return _Verdict("send")


async def _process(auto_send_id: uuid.UUID, org_id: uuid.UUID, token: uuid.UUID) -> str:
    """Handle one claimed row. Returns an outcome label for the tally."""
    context_token = set_context(RequestContext(org_id=org_id))
    try:
        async with async_session() as session:
            found = await auto_send_da.get_claimed(
                session, auto_send_id=auto_send_id, claim_token=token
            )
            if found is None:
                return "gone"
            row, task, lead = found
            now = datetime.now(UTC)
            verdict = await _send_time_verdict(session, row=row, task=task, lead=lead, now=now)

            if verdict.action == "release":
                await _transition(
                    session,
                    row,
                    token,
                    FollowUpAutoSendStatus.claimed,
                    status=FollowUpAutoSendStatus.scheduled,
                    claim_token=None,
                    claimed_at=None,
                )
                await session.commit()
                return "released"
            if verdict.action == "cancel":
                await _transition(
                    session,
                    row,
                    token,
                    FollowUpAutoSendStatus.claimed,
                    status=FollowUpAutoSendStatus.cancelled,
                    reason=verdict.code,
                    cancelled_at=now,
                )
                await session.commit()
                return "cancelled"
            if verdict.action == "skip":
                await _finish_not_sent(
                    session,
                    row=row,
                    task=task,
                    token=token,
                    from_status=FollowUpAutoSendStatus.claimed,
                    status=FollowUpAutoSendStatus.skipped,
                    code=verdict.code,
                )
                return "skipped"

            started = await _transition(
                session,
                row,
                token,
                FollowUpAutoSendStatus.claimed,
                status=FollowUpAutoSendStatus.sending,
                attempts=row.attempts + 1,
                claimed_at=now,
            )
            if not started:
                return "gone"  # cancelled / reaped between claim and send
            await session.commit()

            outcome = await send_template_to_contact(
                session,
                org_id=org_id,
                contact_id=lead.contact_id,
                lead_id=lead.id,
                template_id=row.template_id,
                sender_user_id=task.assigned_to_id,
                extra_payload={"author": "auto_follow_up", "auto_send_id": str(row.id)},
            )
            return await _record_outcome(
                session, row=row, task=task, token=token, outcome=outcome, attempts=row.attempts + 1
            )
    except Exception:
        # The row stays where it is (claimed → released by the reaper;
        # sending → reaped with a message check). Never retried blindly.
        log.exception("auto_send sweep: row %s failed", auto_send_id)
        return "error"
    finally:
        reset_context(context_token)


async def _record_outcome(
    session: AsyncSession,
    *,
    row: FollowUpAutoSend,
    task: Task,
    token: uuid.UUID,
    outcome: SendOutcome,
    attempts: int,
) -> str:
    now = datetime.now(UTC)
    if outcome.kind == "sent":
        await _transition(
            session,
            row,
            token,
            FollowUpAutoSendStatus.sending,
            status=FollowUpAutoSendStatus.sent,
            message_id=outcome.message_id,
            sent_at=now,
            reason=None,
        )
        await activities_service.record_in_session(
            session,
            org_id=row.org_id,
            entity_type="lead",
            entity_id=row.lead_id,
            type=ActivityType(row.channel.value),
            payload={
                "text": f"Auto follow-up sent: “{row.template_name}”",
                "auto_send_id": str(row.id),
                "message_id": str(outcome.message_id) if outcome.message_id else None,
                "status": FollowUpAutoSendStatus.sent.value,
            },
        )
        await session.commit()
        await audit.log(
            "leads.auto_send_sent",
            entity_type="follow_up_auto_send",
            entity_id=row.id,
            after={"message_id": str(outcome.message_id) if outcome.message_id else None},
        )
        await _complete_follow_up(session, task)
        return "sent"

    if outcome.kind == "retry" and attempts < MAX_ATTEMPTS:
        backoff = max(RETRY_BACKOFF, timedelta(seconds=outcome.retry_after_seconds or 0))
        await _transition(
            session,
            row,
            token,
            FollowUpAutoSendStatus.sending,
            status=FollowUpAutoSendStatus.scheduled,
            not_before=now + backoff,
            claim_token=None,
            claimed_at=None,
        )
        await session.commit()
        return "retried"

    status = (
        FollowUpAutoSendStatus.skipped
        if outcome.kind == "skipped"
        else FollowUpAutoSendStatus.failed
    )
    await _finish_not_sent(
        session,
        row=row,
        task=task,
        token=token,
        from_status=FollowUpAutoSendStatus.sending,
        status=status,
        code=outcome.code,
    )
    return status.value


async def _finish_not_sent(
    session: AsyncSession,
    *,
    row: FollowUpAutoSend,
    task: Task,
    token: uuid.UUID,
    from_status: FollowUpAutoSendStatus,
    status: FollowUpAutoSendStatus,
    code: str | None,
) -> None:
    """Record a skip / failure, put it on the lead timeline and tell the
    follow-up's assignee and whoever scheduled it."""
    applied = await _transition(
        session, row, token, from_status, status=status, reason=code, claim_token=None
    )
    if not applied:
        return
    why = reason_text(code)
    await activities_service.record_in_session(
        session,
        org_id=row.org_id,
        entity_type="lead",
        entity_id=row.lead_id,
        type=ActivityType.task,
        payload={
            "text": f"Auto follow-up “{row.template_name}” not sent: {why}",
            "auto_send_id": str(row.id),
            "status": status.value,
            "reason": code,
        },
    )
    await session.commit()
    await audit.log(
        "leads.auto_send_not_sent",
        entity_type="follow_up_auto_send",
        entity_id=row.id,
        after={"status": status.value, "reason": code},
    )
    for user_id in {task.assigned_to_id, row.created_by_id}:
        await notify(
            org_id=row.org_id,
            user_id=user_id,
            type="follow_up.auto_send_failed",
            title="Auto follow-up not sent",
            body=f"“{row.template_name}” wasn't sent because {why}. Please follow up manually.",
            payload={"lead_id": str(row.lead_id), "auto_send_id": str(row.id), "reason": code},
        )


async def _complete_follow_up(session: AsyncSession, task: Task) -> None:
    """A sent auto-message completes its follow-up (owner decision), via
    the tasks service so `task.completed` fires as for a manual close."""
    try:
        await tasks_service.update_task(
            session, task_id=task.id, payload=TaskUpdate(status=TaskStatus.done)
        )
    except Exception:
        log.exception("auto_send sweep: could not complete task %s", task.id)


async def _transition(
    session: AsyncSession,
    row: FollowUpAutoSend,
    token: uuid.UUID,
    from_status: FollowUpAutoSendStatus,
    **values: object,
) -> bool:
    return await auto_send_da.transition(
        session,
        auto_send_id=row.id,
        claim_token=token,
        from_status=from_status,
        values=values,
    )


async def _reap(result: SweepResult) -> None:
    now = datetime.now(UTC)
    async with async_session() as session:
        result.released = await auto_send_da.release_stale_claims(
            session, before=now - STALE_CLAIM_AFTER
        )
        stale = await auto_send_da.list_stale_sending(
            session, before=now - STALE_SENDING_AFTER, limit=_REAP_BATCH
        )
        await session.commit()

    for auto_send_id, org_id, token in stale:
        context_token = set_context(RequestContext(org_id=org_id))
        try:
            async with async_session() as session:
                found = await auto_send_da.get_claimed(
                    session, auto_send_id=auto_send_id, claim_token=token
                )
                if found is None:
                    continue
                row, task, _lead = found
                message_id = await auto_send_da.find_message_id_for_auto_send(
                    session, org_id=org_id, auto_send_id=auto_send_id
                )
                outcome = (
                    SendOutcome("sent", message_id=message_id)
                    if message_id is not None
                    else SendOutcome("failed", "interrupted")
                )
                await _record_outcome(
                    session, row=row, task=task, token=token, outcome=outcome, attempts=MAX_ATTEMPTS
                )
                result.reaped += 1
        except Exception:
            log.exception("auto_send reaper: row %s failed", auto_send_id)
        finally:
            reset_context(context_token)

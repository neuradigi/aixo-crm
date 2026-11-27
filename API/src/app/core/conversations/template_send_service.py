"""Send one saved template to one contact, outside a campaign or workflow.

First caller: the follow-up auto-send (``leads/auto_send``). Every check
that can refuse the send runs **before** a conversation is created or a
provider is called, and the result is a :class:`SendOutcome` rather than
an HTTP error, so a background caller can record why a send did not
happen:

  * ``sent``    — the provider accepted it; ``message_id`` is the row.
  * ``skipped`` — a rule says not to send (opted out, blocked, template
    unusable, no address…). Retrying will not help.
  * ``failed``  — the send could not be completed (provider refused,
    channel not connected, render failed, unknown error). Never retried:
    the message may have gone out.
  * ``retry``   — a definite, harmless rejection (WhatsApp 429); try later.

WhatsApp goes through ``start_conversation`` + ``send_template_message``
(block list, approval, variables, message row, audit). Email renders with
the lead's context and goes through ``send_email`` from the sender's own
live mailbox, else the org's send cascade.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.automation.send_guard import check_dpdp_suppression
from src.app.core.contacts import service as contacts_service
from src.app.core.conversations import service as conversations_service
from src.app.core.conversations.adapters.email import (
    HardCapExceeded,
    MissingCompanyAddress,
    OptedOut,
    send_email,
)
from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppNotConnected,
    WhatsAppRateLimited,
    WhatsAppSendError,
    resolve_whatsapp_adapter,
)
from src.app.core.conversations.exceptions import TemplateSendRejected
from src.app.core.conversations.models import ConversationChannel
from src.app.core.email import data_access as email_da
from src.app.core.integrations.whatsapp.block_list import is_blocked
from src.app.core.integrations.whatsapp.meta_variables import (
    convert_to_positional,
    resolve_named_body_to_positional_params,
)
from src.app.core.templates import data_access as templates_da
from src.app.core.templates import render as templates_render
from src.app.core.templates.models import (
    MessageTemplate,
    TemplateExternalStatus,
    TemplateInternalStatus,
)
from src.app.core.templates.variables import resolve
from src.app.core.tenants import service as tenants_service
from src.app.core.users import service as users_service

log = logging.getLogger(__name__)

OutcomeKind = Literal["sent", "skipped", "failed", "retry"]
_SENDABLE_CHANNELS = (ConversationChannel.whatsapp, ConversationChannel.email)


@dataclass(frozen=True)
class SendOutcome:
    kind: OutcomeKind
    # Fixed reason code for skipped / failed / retry.
    code: str | None = None
    message_id: uuid.UUID | None = None
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class TemplatePreview:
    subject: str | None
    body_text: str
    # The email's designed HTML part; None for WhatsApp and text-only email.
    body_html: str | None
    # Set when the real send could not fill the template for this contact.
    problem: str | None = None


def template_unavailable_reason(template: MessageTemplate | None) -> str | None:
    """Why a library template can't be auto-sent right now, or None.

    Shared by scheduling (refuse up front) and sending (re-check at due
    time — the template may have been archived, deactivated or lost its
    Meta approval since)."""
    if template is None:
        return "template_unavailable"
    if template.channel not in _SENDABLE_CHANNELS:
        return "template_wrong_channel"
    if template.internal_status != TemplateInternalStatus.published or not template.is_active:
        return "template_unavailable"
    if (
        template.channel == ConversationChannel.whatsapp
        and template.external_status != TemplateExternalStatus.approved
    ):
        return "template_not_approved"
    return None


def contact_address(contact: Any, channel: ConversationChannel) -> str | None:
    """The phone (WhatsApp) or email (Email) a send would go to."""
    raw = contact.phone if channel == ConversationChannel.whatsapp else contact.email
    value = (raw or "").strip()
    return value or None


async def send_template_to_contact(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    lead_id: uuid.UUID | None,
    template_id: uuid.UUID,
    sender_user_id: uuid.UUID,
    extra_payload: dict[str, Any] | None = None,
) -> SendOutcome:
    """Send ``template_id`` to the contact. See the module docstring for
    the outcome contract. ``sender_user_id`` is recorded as the sender
    (and, for email, picks their own mailbox when they have one)."""
    contact = await contacts_service.get_contact(session, contact_id)
    if contact is None or contact.org_id != org_id:
        return SendOutcome("skipped", "contact_missing")
    if contact.anonymised_at is not None:
        return SendOutcome("skipped", "contact_anonymised")

    template = await templates_da.get_template(session, org_id=org_id, template_id=template_id)
    unavailable = template_unavailable_reason(template)
    if unavailable is not None or template is None:
        return SendOutcome("skipped", unavailable or "template_unavailable")

    address = contact_address(contact, template.channel)
    if address is None:
        missing = "no_phone" if template.channel == ConversationChannel.whatsapp else "no_email"
        return SendOutcome("skipped", missing)
    if not check_dpdp_suppression(channel=template.channel.value, contact=contact).allow:
        return SendOutcome("skipped", "opted_out")

    payload = dict(extra_payload or {})
    if template.channel == ConversationChannel.whatsapp:
        return await _send_whatsapp(
            session,
            org_id=org_id,
            contact_id=contact_id,
            phone=address,
            template_id=template_id,
            sender_user_id=sender_user_id,
            extra_payload=payload,
        )
    return await _send_email(
        session,
        org_id=org_id,
        contact_id=contact_id,
        lead_id=lead_id,
        template=template,
        sender_user_id=sender_user_id,
        extra_payload=payload,
    )


async def _send_whatsapp(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    phone: str,
    template_id: uuid.UUID,
    sender_user_id: uuid.UUID,
    extra_payload: dict[str, Any],
) -> SendOutcome:
    # Checks that would otherwise only fail after the conversation row
    # is created — so a refused send never leaves an empty thread.
    if await is_blocked(session, org_id=org_id, phone=phone) is not None:
        return SendOutcome("skipped", "blocked")
    try:
        await resolve_whatsapp_adapter(session)
    except WhatsAppNotConnected:
        return SendOutcome("failed", "whatsapp_not_connected")

    try:
        conversation = await conversations_service.start_conversation(
            session, channel=ConversationChannel.whatsapp, contact_id=contact_id
        )
        message = await conversations_service.send_template_message(
            session,
            conversation_id=conversation.id,
            user_id=sender_user_id,
            template_id=template_id,
            variables={},
            extra_payload=extra_payload,
        )
    except TemplateSendRejected as exc:
        return SendOutcome("skipped", exc.code)
    except WhatsAppNotConnected:
        return SendOutcome("failed", "whatsapp_not_connected")
    except WhatsAppRateLimited as exc:
        return SendOutcome("retry", "rate_limited", retry_after_seconds=exc.retry_after_seconds)
    except WhatsAppSendError:
        log.warning("template_send: Meta refused template=%s contact=%s", template_id, contact_id)
        return SendOutcome("failed", "provider_rejected")
    except Exception:
        # Unknown outcome (timeout, network) — the message may have
        # gone out, so this is final, never retried.
        log.exception("template_send: whatsapp send error contact=%s", contact_id)
        return SendOutcome("failed", "send_error")
    return SendOutcome("sent", message_id=message.id)


async def _send_email(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    lead_id: uuid.UUID | None,
    template: MessageTemplate,
    sender_user_id: uuid.UUID,
    extra_payload: dict[str, Any],
) -> SendOutcome:
    try:
        context = await _email_context(
            session,
            org_id=org_id,
            contact_id=contact_id,
            lead_id=lead_id,
            sender_user_id=sender_user_id,
        )
        rendered = templates_render.render_email_template(template, context)
    except HTTPException:
        return SendOutcome("failed", "render_failed")

    account = await email_da.find_live_account_for_user(
        session, org_id=org_id, user_id=sender_user_id
    )
    try:
        result = await send_email(
            session,
            org_id=org_id,
            sender_user_id=sender_user_id,
            account_id=account.id if account is not None else None,
            contact_id=contact_id,
            subject=rendered["subject"] or template.name,
            body_text=rendered["body_text"],
            body_html=rendered["body_html"],
            extra_payload=extra_payload,
        )
    except OptedOut:
        return SendOutcome("skipped", "opted_out")
    except HardCapExceeded:
        return SendOutcome("failed", "mailbox_daily_cap")
    except MissingCompanyAddress:
        return SendOutcome("failed", "missing_company_address")
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = str(detail.get("skip_code") or "email_not_sendable")
        log.warning("template_send: email refused code=%s contact=%s", code, contact_id)
        return SendOutcome("failed", code)
    except Exception:
        log.exception("template_send: email send error contact=%s", contact_id)
        return SendOutcome("failed", "send_error")
    return SendOutcome("sent", message_id=result.message.id)


async def _email_context(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    lead_id: uuid.UUID | None,
    sender_user_id: uuid.UUID,
) -> dict[str, Any]:
    """The variables an email template is filled from: contact, lead,
    sender and org. Raises HTTP 404 when the contact is gone."""
    org = await tenants_service.get_organization_by_id(session, org_id)
    sender = await users_service.get_user_by_uuid(session, sender_user_id)
    sender_info = getattr(sender, "info", None)
    return await templates_render.build_context(
        session,
        org=org,
        contact_id=contact_id,
        lead_id=lead_id,
        sender_user_id=sender_user_id,
        sender_first_name=getattr(sender_info, "first_name", None),
        sender_last_name=getattr(sender_info, "last_name", None),
        sender_email=getattr(sender, "email", None),
    )


async def preview_template_for_contact(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    lead_id: uuid.UUID | None,
    template: MessageTemplate,
    sender_user_id: uuid.UUID,
) -> TemplatePreview:
    """What :func:`send_template_to_contact` would send this contact,
    filled the same way: WhatsApp from the contact + org (a blank value
    becomes the fallback Meta is given), email from the contact, lead,
    sender and org. Sends nothing."""
    if template.channel == ConversationChannel.whatsapp:
        named_body = template.body_text or ""
        contact_data, org_data = await conversations_service.named_variable_data(
            session, org_id=org_id, contact_id=contact_id
        )
        text, _ = convert_to_positional(named_body)
        params = resolve_named_body_to_positional_params(named_body, contact_data, org_data)
        for index, value in params.items():
            text = text.replace("{{" + str(index) + "}}", value)
        return TemplatePreview(subject=None, body_text=text, body_html=None)

    context = await _email_context(
        session,
        org_id=org_id,
        contact_id=contact_id,
        lead_id=lead_id,
        sender_user_id=sender_user_id,
    )
    has_design = bool(template.body_html)
    try:
        rendered = templates_render.render_email_template(template, context)
    except HTTPException:
        # The send would fail (`render_failed`); show what is known.
        return TemplatePreview(
            subject=resolve(template.subject or "", context) or template.name,
            body_text=resolve(template.body_text or "", context, autoescape=False),
            body_html=resolve(template.body_html or "", context) if has_design else None,
            problem=(
                "Some fields in this template have no value for this lead, "
                "so the email would not be sent."
            ),
        )
    return TemplatePreview(
        subject=rendered["subject"] or template.name,
        body_text=rendered["body_text"],
        body_html=rendered["body_html"] if has_design else None,
    )

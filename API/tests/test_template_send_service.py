"""`send_template_to_contact` (tasks/follow-up-auto-send Step 2).

Pure decision logic: every refusal is decided before a conversation is
created or a provider is called, and each provider outcome maps to the
right `SendOutcome`. Database and provider calls are replaced with
doubles, so these run without a test database.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.app.core.conversations import template_send_service as svc
from src.app.core.conversations.adapters.email import HardCapExceeded, OptedOut
from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppNotConnected,
    WhatsAppRateLimited,
    WhatsAppSendError,
)
from src.app.core.conversations.exceptions import TemplateSendRejected
from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates.models import TemplateExternalStatus, TemplateInternalStatus

ORG = uuid.uuid4()
SENDER = uuid.uuid4()


def _contact(**overrides):
    values = dict(
        id=uuid.uuid4(),
        org_id=ORG,
        anonymised_at=None,
        phone="+919000000001",
        email="asha@example.com",
        whatsapp_opt_in_status="implicit",
        email_opt_out=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _template(channel=ConversationChannel.whatsapp, **overrides):
    values = dict(
        id=uuid.uuid4(),
        name="Following up",
        channel=channel,
        internal_status=TemplateInternalStatus.published,
        external_status=(
            TemplateExternalStatus.approved
            if channel == ConversationChannel.whatsapp
            else TemplateExternalStatus.n_a
        ),
        is_active=True,
        subject="Hello",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def calls():
    return {"start_conversation": 0, "send_template": [], "send_email": []}


@pytest.fixture
def world(monkeypatch, calls):
    """Default doubles: a sendable contact + WhatsApp template, nothing
    blocked, WhatsApp connected, every send succeeds."""
    state = {"contact": _contact(), "template": _template(), "blocked": False, "account": None}

    async def get_contact(session, contact_id):
        return state["contact"]

    async def get_template(session, *, org_id, template_id):
        return state["template"]

    async def is_blocked(session, *, org_id, phone):
        return object() if state["blocked"] else None

    async def resolve_adapter(session, *, phone_id=None):
        return object()

    async def start_conversation(session, *, channel, contact_id):
        calls["start_conversation"] += 1
        return SimpleNamespace(id=uuid.uuid4())

    async def send_template_message(session, **kwargs):
        calls["send_template"].append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(svc.contacts_service, "get_contact", get_contact)
    monkeypatch.setattr(svc.templates_da, "get_template", get_template)
    monkeypatch.setattr(svc, "is_blocked", is_blocked)
    monkeypatch.setattr(svc, "resolve_whatsapp_adapter", resolve_adapter)
    monkeypatch.setattr(svc.conversations_service, "start_conversation", start_conversation)
    monkeypatch.setattr(svc.conversations_service, "send_template_message", send_template_message)
    return state


async def _send(**overrides):
    kwargs = dict(
        org_id=ORG,
        contact_id=uuid.uuid4(),
        lead_id=uuid.uuid4(),
        template_id=uuid.uuid4(),
        sender_user_id=SENDER,
        extra_payload={"author": "auto_follow_up", "auto_send_id": "abc"},
    )
    kwargs.update(overrides)
    return await svc.send_template_to_contact(None, **kwargs)


# --- template_unavailable_reason ---------------------------------------------


@pytest.mark.parametrize(
    ("template", "code"),
    [
        (None, "template_unavailable"),
        (_template(), None),
        (_template(ConversationChannel.email), None),
        (_template(channel=ConversationChannel.sms), "template_wrong_channel"),
        (_template(internal_status=TemplateInternalStatus.archived), "template_unavailable"),
        (_template(is_active=False), "template_unavailable"),
        (_template(external_status=TemplateExternalStatus.pending), "template_not_approved"),
    ],
)
def test_template_unavailable_reason(template, code):
    assert svc.template_unavailable_reason(template) == code


# --- refusals before any conversation / provider call ------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"contact": None}, "contact_missing"),
        ({"contact": _contact(org_id=uuid.uuid4())}, "contact_missing"),
        ({"contact": _contact(anonymised_at="2026-01-01")}, "contact_anonymised"),
        ({"contact": _contact(phone=None)}, "no_phone"),
        ({"contact": _contact(whatsapp_opt_in_status="opted_out")}, "opted_out"),
        ({"blocked": True}, "blocked"),
        ({"template": _template(is_active=False)}, "template_unavailable"),
    ],
)
async def test_refusals_create_no_conversation(world, calls, change, code):
    world.update(change)
    outcome = await _send()
    assert (outcome.kind, outcome.code) == ("skipped", code)
    assert calls["start_conversation"] == 0


@pytest.mark.asyncio
async def test_whatsapp_not_connected_is_checked_first(world, calls, monkeypatch):
    async def not_connected(session, *, phone_id=None):
        raise WhatsAppNotConnected()

    monkeypatch.setattr(svc, "resolve_whatsapp_adapter", not_connected)
    outcome = await _send()
    assert (outcome.kind, outcome.code) == ("failed", "whatsapp_not_connected")
    assert calls["start_conversation"] == 0


# --- WhatsApp provider outcomes ----------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_sent_carries_the_markers(world, calls):
    outcome = await _send()
    assert outcome.kind == "sent" and outcome.message_id is not None
    sent = calls["send_template"][0]
    assert sent["user_id"] == SENDER
    assert sent["extra_payload"] == {"author": "auto_follow_up", "auto_send_id": "abc"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "kind", "code"),
    [
        (WhatsAppRateLimited("slow down", retry_after_seconds=30), "retry", "rate_limited"),
        (WhatsAppSendError("bad"), "failed", "provider_rejected"),
        (
            TemplateSendRejected("template_variables_missing", "x"),
            "skipped",
            "template_variables_missing",
        ),
        (TimeoutError(), "failed", "send_error"),
    ],
)
async def test_whatsapp_errors_map_to_outcomes(world, monkeypatch, error, kind, code):
    async def failing_send(session, **kwargs):
        raise error

    monkeypatch.setattr(svc.conversations_service, "send_template_message", failing_send)
    outcome = await _send()
    assert (outcome.kind, outcome.code) == (kind, code)
    if kind == "retry":
        assert outcome.retry_after_seconds == 30


# --- Email -------------------------------------------------------------------


@pytest.fixture
def email_world(world, monkeypatch, calls):
    world["template"] = _template(ConversationChannel.email)

    async def get_org(session, org_id):
        return SimpleNamespace(id=org_id, name="Acme")

    async def get_user(session, user_uuid):
        return SimpleNamespace(
            info=SimpleNamespace(first_name="Priya", last_name="S"), email="priya@acme.test"
        )

    async def build_context(session, **kwargs):
        return {"contact": {}}

    def render(template, context):
        return {"subject": "Hi", "body_text": "Body", "body_html": "<p>Body</p>"}

    async def find_account(session, *, org_id, user_id):
        return world["account"]

    async def send_email(session, **kwargs):
        calls["send_email"].append(kwargs)
        return SimpleNamespace(message=SimpleNamespace(id=uuid.uuid4()))

    monkeypatch.setattr(svc.tenants_service, "get_organization_by_id", get_org)
    monkeypatch.setattr(svc.users_service, "get_user_by_uuid", get_user)
    monkeypatch.setattr(svc.templates_render, "build_context", build_context)
    monkeypatch.setattr(svc.templates_render, "render_email_template", render)
    monkeypatch.setattr(svc.email_da, "find_live_account_for_user", find_account)
    monkeypatch.setattr(svc, "send_email", send_email)
    return world


@pytest.mark.asyncio
async def test_email_uses_the_senders_own_mailbox(email_world, calls):
    email_world["account"] = SimpleNamespace(id=uuid.uuid4())
    outcome = await _send()
    assert outcome.kind == "sent"
    assert calls["send_email"][0]["account_id"] == email_world["account"].id
    assert calls["send_email"][0]["extra_payload"]["auto_send_id"] == "abc"


@pytest.mark.asyncio
async def test_email_falls_back_to_the_org_cascade(email_world, calls):
    outcome = await _send()
    assert outcome.kind == "sent"
    assert calls["send_email"][0]["account_id"] is None


@pytest.mark.asyncio
async def test_email_opted_out_is_skipped_before_sending(email_world, calls):
    email_world["contact"] = _contact(email_opt_out=True)
    outcome = await _send()
    assert (outcome.kind, outcome.code) == ("skipped", "opted_out")
    assert calls["send_email"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "kind", "code"),
    [
        (OptedOut(contact_id=uuid.uuid4()), "skipped", "opted_out"),
        (HardCapExceeded(sent=100, cap=100), "failed", "mailbox_daily_cap"),
        (
            HTTPException(429, detail={"skip_code": "reputation_paused"}),
            "failed",
            "reputation_paused",
        ),
        (HTTPException(400, detail="No sending path"), "failed", "email_not_sendable"),
    ],
)
async def test_email_errors_map_to_outcomes(email_world, monkeypatch, error, kind, code):
    async def failing_send(session, **kwargs):
        raise error

    monkeypatch.setattr(svc, "send_email", failing_send)
    outcome = await _send()
    assert (outcome.kind, outcome.code) == (kind, code)


@pytest.mark.asyncio
async def test_email_render_failure_is_failed(email_world, monkeypatch, calls):
    def bad_render(template, context):
        raise HTTPException(400, detail="missing variables")

    monkeypatch.setattr(svc.templates_render, "render_email_template", bad_render)
    outcome = await _send()
    assert (outcome.kind, outcome.code) == ("failed", "render_failed")
    assert calls["send_email"] == []

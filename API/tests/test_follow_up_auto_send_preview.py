"""Auto-send preview filled with the lead's details (tasks/follow-up-auto-send
Step 11).

The preview fills a template exactly as the send does — WhatsApp from the
contact + org with Meta's blank fallback, email from the full lead context
— and an email template's designed HTML is the HTML part, in the preview
and in the real send. Database lookups are doubles.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.app.core.conversations import template_send_service as tsvc
from src.app.core.conversations.models import ConversationChannel
from src.app.core.leads.auto_send import service as svc
from src.app.core.leads.auto_send.models import FollowUpAutoSendChannel
from src.app.core.templates.render import render_email_template

ORG = uuid.uuid4()
CONTEXT = {
    "contact": {"first_name": "Ajay", "full_name": "Ajay Gogane", "last_name": ""},
    "org": {"name": "Acme Homes"},
}


def _template(channel=ConversationChannel.email, **overrides):
    values = dict(
        id=uuid.uuid4(),
        name="Following up",
        channel=channel,
        subject="Hi {{contact.first_name}}",
        body_text="Dear {{ contact.first_name }}, from {{org.name}}",
        body_html=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


async def _preview(template):
    return await tsvc.preview_template_for_contact(
        object(),
        org_id=ORG,
        contact_id=uuid.uuid4(),
        lead_id=uuid.uuid4(),
        template=template,
        sender_user_id=uuid.uuid4(),
    )


@pytest.fixture
def contexts(monkeypatch):
    async def named(session, *, org_id, contact_id):
        return CONTEXT["contact"], CONTEXT["org"]

    async def email_context(session, **kwargs):
        return CONTEXT

    monkeypatch.setattr(tsvc.conversations_service, "named_variable_data", named)
    monkeypatch.setattr(tsvc, "_email_context", email_context)


# --- filling -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_fills_from_contact_and_org_with_metas_blank_fallback(contexts):
    template = _template(
        ConversationChannel.whatsapp,
        body_text="Hello {{ contact.full_name }} from {{org.name}} {{contact.last_name}}",
    )
    preview = await _preview(template)
    assert preview.body_text == "Hello Ajay Gogane from Acme Homes Customer"
    assert preview.subject is None and preview.body_html is None


@pytest.mark.asyncio
async def test_email_fills_subject_text_and_design(contexts):
    preview = await _preview(_template(body_html="<p>Dear {{contact.first_name}}</p>"))
    assert preview.subject == "Hi Ajay"
    assert preview.body_text == "Dear Ajay, from Acme Homes"
    assert preview.body_html == "<p>Dear Ajay</p>"
    assert preview.problem is None


@pytest.mark.asyncio
async def test_text_only_email_has_no_html_preview(contexts):
    preview = await _preview(_template())
    assert preview.body_html is None
    assert preview.body_text == "Dear Ajay, from Acme Homes"


@pytest.mark.asyncio
async def test_email_the_send_could_not_fill_says_so(contexts):
    preview = await _preview(_template(body_text="Budget: {{contact.custom_data.budget}}"))
    assert preview.problem is not None
    assert preview.body_text == "Budget: "


def test_the_real_email_send_uses_the_templates_design():
    designed = render_email_template(_template(body_html="<b>{{contact.first_name}}</b>"), CONTEXT)
    assert designed["body_html"] == "<b>Ajay</b>"
    assert designed["body_text"] == "Dear Ajay, from Acme Homes"
    plain = render_email_template(_template(), CONTEXT)
    assert plain["body_html"] == "Dear Ajay, from Acme Homes"


# --- auto-send wrapper ----------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_auto_send_fills_for_the_leads_contact(monkeypatch):
    template = _template(ConversationChannel.whatsapp)
    seen = {}

    async def get_template(session, *, org_id, template_id):
        return template

    async def preview(session, **kwargs):
        seen.update(kwargs)
        return tsvc.TemplatePreview(subject=None, body_text="Hello Ajay", body_html=None)

    monkeypatch.setattr(svc.templates_da, "get_template", get_template)
    monkeypatch.setattr(svc, "preview_template_for_contact", preview)
    lead = SimpleNamespace(id=uuid.uuid4(), contact_id=uuid.uuid4())
    sender = uuid.uuid4()
    result = await svc.preview_auto_send(
        object(), org_id=ORG, lead=lead, template_id=template.id, sender_user_id=sender
    )
    assert result.channel == FollowUpAutoSendChannel.whatsapp
    assert result.body_text == "Hello Ajay"
    assert (seen["contact_id"], seen["lead_id"], seen["sender_user_id"]) == (
        lead.contact_id,
        lead.id,
        sender,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("template", [None, _template(ConversationChannel.sms)])
async def test_preview_auto_send_404s_for_a_template_it_cannot_send(monkeypatch, template):
    async def get_template(session, *, org_id, template_id):
        return template

    monkeypatch.setattr(svc.templates_da, "get_template", get_template)
    lead = SimpleNamespace(id=uuid.uuid4(), contact_id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        await svc.preview_auto_send(
            object(), org_id=ORG, lead=lead, template_id=uuid.uuid4(), sender_user_id=uuid.uuid4()
        )
    assert exc.value.status_code == 404

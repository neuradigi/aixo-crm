"""`stage_auto_send` scheduling rules (tasks/follow-up-auto-send Step 3).

Every rule refuses with a fixed `error` code before anything is
written; one pending auto-send per person (409 unless `replace`), and
Replace cancels the old row. Database and provider calls are doubles,
so these run without a test database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.app.core.conversations.adapters.whatsapp import WhatsAppNotConnected
from src.app.core.conversations.models import ConversationChannel
from src.app.core.email_sender_setup.service import SendNotConfiguredError
from src.app.core.leads.auto_send import service as svc
from src.app.core.leads.auto_send.models import FollowUpAutoSendChannel, FollowUpAutoSendStatus
from src.app.core.tasks.models import TaskFollowupType
from src.app.core.templates.models import (
    TemplateCategory,
    TemplateExternalStatus,
    TemplateInternalStatus,
)

ORG = uuid.uuid4()
ACTOR = uuid.uuid4()


class _Session:
    async def flush(self):
        return None


def _template(channel=ConversationChannel.whatsapp, **overrides):
    values = dict(
        id=uuid.uuid4(),
        name="Following up",
        channel=channel,
        category=TemplateCategory.transactional,
        internal_status=TemplateInternalStatus.published,
        external_status=(
            TemplateExternalStatus.approved
            if channel == ConversationChannel.whatsapp
            else TemplateExternalStatus.n_a
        ),
        is_active=True,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _contact(**overrides):
    values = dict(
        id=uuid.uuid4(),
        full_name="Asha",
        anonymised_at=None,
        phone="+919000000001",
        email="asha@example.com",
        whatsapp_opt_in_status="implicit",
        email_opt_out=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _pending_row(status=FollowUpAutoSendStatus.scheduled):
    return SimpleNamespace(
        id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        lead_id=uuid.uuid4(),
        status=status,
        channel=FollowUpAutoSendChannel.whatsapp,
        template_name="Older",
        reason=None,
        created_by_id=uuid.uuid4(),
    )


@pytest.fixture
def world(monkeypatch):
    state = {
        "template": _template(),
        "contact": _contact(),
        "blocked": False,
        "wa_connected": True,
        "mailbox": None,
        "envelope_ok": True,
        "quiet": False,
        "count_today": 0,
        "pending": [],
        "cancel_returns": None,
        "inserted": [],
        "activities": [],
        "cancelled": [],
    }

    async def get_template(session, *, org_id, template_id):
        return state["template"]

    async def lock_contacts(session, *, org_id, contact_ids):
        return [state["contact"]] if state["contact"] else []

    async def is_blocked(session, *, org_id, phone):
        return object() if state["blocked"] else None

    async def resolve_adapter(session, *, phone_id=None):
        if not state["wa_connected"]:
            raise WhatsAppNotConnected()
        return object()

    async def find_mailbox(session, *, org_id, user_id):
        return state["mailbox"]

    async def resolve_envelope(session, *, org_id, caller_supplied_sender_id=None):
        if not state["envelope_ok"]:
            raise SendNotConfiguredError("none")
        return object()

    async def quiet(session, *, org_id, at, category):
        return state["quiet"]

    async def count_created(session, *, org_id, user_id, since):
        return state["count_today"]

    async def list_pending(session, *, org_id, contact_id):
        return state["pending"]

    async def cancel(session, *, org_id, ids, cancelled_by_id, reason, now):
        state["cancelled"].append((ids, reason))
        return ids if state["cancel_returns"] is None else state["cancel_returns"]

    def insert(session, row):
        row.id = uuid.uuid4()
        row.status = FollowUpAutoSendStatus.scheduled
        state["inserted"].append(row)
        return row

    async def record(session, **kwargs):
        state["activities"].append(kwargs)

    monkeypatch.setattr(svc.templates_da, "get_template", get_template)
    monkeypatch.setattr(svc.contacts_da, "lock_contacts", lock_contacts)
    monkeypatch.setattr(svc, "is_blocked", is_blocked)
    monkeypatch.setattr(svc, "resolve_whatsapp_adapter", resolve_adapter)
    monkeypatch.setattr(svc.email_da, "find_live_account_for_user", find_mailbox)
    monkeypatch.setattr(svc, "resolve_send_envelope", resolve_envelope)
    monkeypatch.setattr(svc, "falls_in_quiet_hours", quiet)
    monkeypatch.setattr(svc.auto_send_da, "count_auto_sends_created_by", count_created)
    monkeypatch.setattr(svc.auto_send_da, "list_pending_auto_sends_for_contact", list_pending)
    monkeypatch.setattr(svc.auto_send_da, "cancel_pending_auto_sends", cancel)
    monkeypatch.setattr(svc.auto_send_da, "insert_auto_send", insert)
    monkeypatch.setattr(svc.activities_service, "record_in_session", record)
    return state


async def _stage(followup_type=TaskFollowupType.whatsapp, due_in=timedelta(days=1), **kw):
    task = SimpleNamespace(
        id=uuid.uuid4(),
        due_at=datetime.now(UTC) + due_in,
        followup_type=followup_type,
        assigned_to_id=ACTOR,
    )
    lead = SimpleNamespace(id=uuid.uuid4(), contact_id=uuid.uuid4())
    return await svc.stage_auto_send(
        _Session(),
        org_id=ORG,
        lead=lead,
        task=task,
        template_id=uuid.uuid4(),
        actor_id=ACTOR,
        lead_closing=kw.get("lead_closing", False),
        replace=kw.get("replace", False),
    )


async def _expect(code: str, status: int = 422, **kw):
    with pytest.raises(HTTPException) as exc:
        await _stage(**kw)
    assert exc.value.status_code == status
    assert exc.value.detail["error"] == code
    return exc.value


@pytest.mark.asyncio
async def test_schedules_and_writes_a_timeline_entry(world):
    staged = await _stage()
    assert staged.row.recipient == "+919000000001"
    assert staged.row.channel == FollowUpAutoSendChannel.whatsapp
    assert staged.replaced == []
    assert world["activities"][0]["payload"]["status"] == "scheduled"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "kwargs", "code"),
    [
        ({}, {"followup_type": TaskFollowupType.call}, "auto_send_type"),
        ({"template": None}, {}, "auto_send_template_unavailable"),
        (
            {"template": _template(external_status=TemplateExternalStatus.pending)},
            {},
            "auto_send_template_unavailable",
        ),
        ({"template": _template(ConversationChannel.email)}, {}, "auto_send_template_channel"),
        ({}, {"lead_closing": True}, "auto_send_lead_closed"),
        ({}, {"due_in": -timedelta(hours=1)}, "auto_send_past_due"),
        ({}, {"due_in": timedelta(days=91)}, "auto_send_too_far"),
        ({"contact": _contact(anonymised_at="2026-01-01")}, {}, "auto_send_contact_unavailable"),
        ({"contact": _contact(phone=None)}, {}, "auto_send_no_address"),
        (
            {"contact": _contact(whatsapp_opt_in_status="opted_out")},
            {},
            "auto_send_opted_out",
        ),
        ({"blocked": True}, {}, "auto_send_blocked"),
        ({"wa_connected": False}, {}, "auto_send_channel_not_connected"),
        ({"quiet": True}, {}, "auto_send_quiet_hours"),
        ({"count_today": svc.AUTO_SEND_DAILY_CAP_PER_USER}, {}, "auto_send_daily_limit"),
    ],
)
async def test_each_rule_refuses_before_writing(world, change, kwargs, code):
    world.update(change)
    await _expect(code, **kwargs)
    assert world["inserted"] == [] and world["activities"] == []


@pytest.mark.asyncio
async def test_a_few_minutes_in_the_past_is_still_allowed(world):
    await _stage(due_in=-timedelta(minutes=2))
    assert len(world["inserted"]) == 1


@pytest.mark.asyncio
async def test_email_needs_a_mailbox_or_a_sending_path(world):
    world["template"] = _template(ConversationChannel.email)
    world["envelope_ok"] = False
    await _expect("auto_send_channel_not_connected", followup_type=TaskFollowupType.email)
    world["mailbox"] = SimpleNamespace(id=uuid.uuid4())  # the assignee's own mailbox is enough
    staged = await _stage(followup_type=TaskFollowupType.email)
    assert staged.row.recipient == "asha@example.com"


@pytest.mark.asyncio
async def test_second_pending_for_the_person_is_409_with_the_existing_one(world):
    older = _pending_row()
    world["pending"] = [(older, datetime.now(UTC) + timedelta(hours=3))]
    exc = await _expect("auto_send_exists", status=409)
    assert exc.detail["existing"]["template_name"] == "Older"
    assert world["cancelled"] == []


@pytest.mark.asyncio
async def test_replace_cancels_the_old_one_and_schedules(world):
    older = _pending_row()
    world["pending"] = [(older, None)]
    staged = await _stage(replace=True)
    assert world["cancelled"] == [([older.id], "replaced")]
    assert staged.replaced == [older]
    assert len(world["inserted"]) == 1
    texts = [a["payload"]["text"] for a in world["activities"]]
    assert any("replaced" in t for t in texts)


@pytest.mark.asyncio
async def test_replace_refuses_while_the_old_one_is_sending(world):
    older = _pending_row()
    world["pending"] = [(older, None)]
    world["cancel_returns"] = []  # a sweep moved it to `sending` meanwhile
    await _expect("auto_send_sending", status=409, replace=True)
    assert world["inserted"] == []

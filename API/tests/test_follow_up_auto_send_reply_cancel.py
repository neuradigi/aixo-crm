"""Cancel on reply (tasks/follow-up-auto-send Step 6).

When the contact messages us first, their scheduled (or claimed) auto-send
is cancelled with `lead_replied` and the assignee + scheduler are told; a
row already `sending` is left alone. Doubles replace the DB, so these run
without a test database.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.app.core.events import bus
from src.app.core.events.event_catalog import EMAIL_MESSAGE_RECEIVED, WHATSAPP_MESSAGE_RECEIVED
from src.app.core.leads.auto_send import service as svc
from src.app.core.leads.auto_send import subscribers
from src.app.core.leads.auto_send.models import FollowUpAutoSendStatus

ORG = uuid.uuid4()
CONTACT = uuid.uuid4()


class _Session:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _row(status):
    return SimpleNamespace(
        id=uuid.uuid4(),
        lead_id=uuid.uuid4(),
        template_name="Following up",
        status=status,
        created_by_id=uuid.uuid4(),
    )


@pytest.fixture
def world(monkeypatch):
    state = {"pending": [], "cancelled_ids": [], "activities": [], "notified": []}
    task = SimpleNamespace(assigned_to_id=uuid.uuid4())
    by_id = {}

    async def list_pending(session, *, org_id, contact_id):
        for row, _ in state["pending"]:
            by_id[row.id] = row
        return state["pending"]

    async def cancel(session, *, org_id, ids, cancelled_by_id, reason, now):
        assert reason == "lead_replied" and cancelled_by_id is None
        state["cancelled_ids"].extend(ids)
        return ids

    async def get_auto_send(session, *, org_id, auto_send_id):
        return (by_id[auto_send_id], task)

    async def record(session, **kwargs):
        state["activities"].append(kwargs)

    async def audit_log(action, **kwargs):
        return None

    async def notify(**kwargs):
        state["notified"].append(kwargs["user_id"])

    monkeypatch.setattr(svc.auto_send_da, "list_pending_auto_sends_for_contact", list_pending)
    monkeypatch.setattr(svc.auto_send_da, "cancel_pending_auto_sends", cancel)
    monkeypatch.setattr(svc.auto_send_da, "get_auto_send", get_auto_send)
    monkeypatch.setattr(svc.activities_service, "record_in_session", record)
    monkeypatch.setattr(svc.audit, "log", audit_log)
    monkeypatch.setattr(svc, "notify", notify)
    state["task"] = task
    return state


@pytest.mark.asyncio
async def test_reply_cancels_the_scheduled_message_and_tells_people(world):
    row = _row(FollowUpAutoSendStatus.scheduled)
    world["pending"] = [(row, None)]
    session = _Session()
    assert await svc.cancel_on_reply(session, org_id=ORG, contact_id=CONTACT) == 1
    assert world["cancelled_ids"] == [row.id]
    assert session.commits == 1
    assert world["activities"][0]["payload"]["reason"] == "lead_replied"
    assert set(world["notified"]) == {world["task"].assigned_to_id, row.created_by_id}


@pytest.mark.asyncio
async def test_a_message_already_sending_is_left_alone(world):
    world["pending"] = [(_row(FollowUpAutoSendStatus.sending), None)]
    session = _Session()
    assert await svc.cancel_on_reply(session, org_id=ORG, contact_id=CONTACT) == 0
    assert world["cancelled_ids"] == [] and session.commits == 0
    assert world["notified"] == []


@pytest.mark.asyncio
async def test_no_pending_message_does_nothing(world):
    session = _Session()
    assert await svc.cancel_on_reply(session, org_id=ORG, contact_id=CONTACT) == 0
    assert session.commits == 0


def test_subscribed_to_both_inbound_events():
    assert subscribers.on_inbound_message in bus._subscribers[WHATSAPP_MESSAGE_RECEIVED]
    assert subscribers.on_inbound_message in bus._subscribers[EMAIL_MESSAGE_RECEIVED]


@pytest.mark.asyncio
async def test_handler_ignores_messages_without_a_contact(monkeypatch):
    called = []

    async def cancel_on_reply(session, **kwargs):
        called.append(kwargs)

    monkeypatch.setattr(svc, "cancel_on_reply", cancel_on_reply)
    await subscribers.on_inbound_message({"org_id": str(ORG), "contact_id": None})
    await subscribers.on_inbound_message({"org_id": "not-a-uuid", "contact_id": str(CONTACT)})
    assert called == []

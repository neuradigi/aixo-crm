"""Cancel + reschedule guard (tasks/follow-up-auto-send Step 4).

Decision logic with doubles for the DB, so these run without a test
database: what can be cancelled (409 while sending / once final), who is
told, and which new follow-up times are refused while an auto-message is
scheduled. Housekeeping's SQL and the list summaries are exercised
against a real database by the step's verification script.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.app.core.leads.auto_send import service as svc
from src.app.core.leads.auto_send.models import FollowUpAutoSendChannel, FollowUpAutoSendStatus
from src.app.core.templates.models import TemplateCategory

ORG = uuid.uuid4()
ACTOR = uuid.uuid4()
CREATOR = uuid.uuid4()
ASSIGNEE = uuid.uuid4()


class _Session:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _row(status=FollowUpAutoSendStatus.scheduled):
    return SimpleNamespace(
        id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        lead_id=uuid.uuid4(),
        template_id=uuid.uuid4(),
        template_name="Following up",
        status=status,
        channel=FollowUpAutoSendChannel.whatsapp,
        reason=None,
        created_by_id=CREATOR,
    )


@pytest.fixture
def world(monkeypatch):
    state = {
        "row": _row(),
        "cancel_ok": True,
        "quiet": False,
        "notified": [],
        "activities": [],
    }
    task = SimpleNamespace(assigned_to_id=ASSIGNEE, due_at=datetime.now(UTC) + timedelta(days=1))

    async def get_auto_send(session, *, org_id, auto_send_id):
        return (state["row"], task) if state["row"] else None

    async def get_for_task(session, *, org_id, task_id):
        return state["row"]

    async def cancel(session, *, org_id, ids, cancelled_by_id, reason, now):
        return ids if state["cancel_ok"] else []

    async def record(session, **kwargs):
        state["activities"].append(kwargs)

    async def audit_log(action, **kwargs):
        return None

    async def notify(**kwargs):
        state["notified"].append(kwargs["user_id"])

    async def get_template(session, *, org_id, template_id):
        return SimpleNamespace(category=TemplateCategory.marketing)

    async def quiet(session, *, org_id, at, category):
        return state["quiet"]

    monkeypatch.setattr(svc.auto_send_da, "get_auto_send", get_auto_send)
    monkeypatch.setattr(svc.auto_send_da, "get_auto_send_for_task", get_for_task)
    monkeypatch.setattr(svc.auto_send_da, "cancel_pending_auto_sends", cancel)
    monkeypatch.setattr(svc.activities_service, "record_in_session", record)
    monkeypatch.setattr(svc.audit, "log", audit_log)
    monkeypatch.setattr(svc, "notify", notify)
    monkeypatch.setattr(svc.templates_da, "get_template", get_template)
    monkeypatch.setattr(svc, "falls_in_quiet_hours", quiet)
    return state


async def _cancel(actor=ACTOR):
    session = _Session()
    summary = await svc.cancel_auto_send(
        session, org_id=ORG, auto_send_id=uuid.uuid4(), actor_id=actor
    )
    return session, summary


# --- cancel ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_commits_writes_activity_and_tells_creator_and_assignee(world):
    session, _ = await _cancel()
    assert session.commits == 1
    assert world["activities"][0]["payload"]["status"] == "cancelled"
    assert sorted(world["notified"]) == sorted([CREATOR, ASSIGNEE])


@pytest.mark.asyncio
async def test_cancel_by_the_creator_does_not_notify_the_creator(world):
    await _cancel(actor=CREATOR)
    assert world["notified"] == [ASSIGNEE]


@pytest.mark.asyncio
async def test_cancel_while_sending_is_409(world):
    world["row"] = _row(FollowUpAutoSendStatus.sending)
    with pytest.raises(HTTPException) as exc:
        await _cancel()
    assert exc.value.status_code == 409 and exc.value.detail["error"] == "auto_send_sending"


@pytest.mark.asyncio
async def test_cancel_after_it_finished_is_409(world):
    world["cancel_ok"] = False  # compare-and-set found it already sent / cancelled
    with pytest.raises(HTTPException) as exc:
        await _cancel()
    assert exc.value.detail["error"] == "auto_send_not_pending"
    assert world["activities"] == []


@pytest.mark.asyncio
async def test_cancel_unknown_id_is_404(world):
    world["row"] = None
    with pytest.raises(HTTPException) as exc:
        await _cancel()
    assert exc.value.status_code == 404


# --- reschedule guard --------------------------------------------------------


async def _guard(new_due_at):
    await svc.guard_reschedule(object(), org_id=ORG, task_id=uuid.uuid4(), new_due_at=new_due_at)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("offset", "code"),
    [
        (None, "auto_send_due_required"),
        (-timedelta(hours=2), "auto_send_past_due"),
        (timedelta(days=91), "auto_send_too_far"),
    ],
)
async def test_guard_refuses_times_the_message_cannot_go_out_at(world, offset, code):
    new_due = None if offset is None else datetime.now(UTC) + offset
    with pytest.raises(HTTPException) as exc:
        await _guard(new_due)
    assert exc.value.detail["error"] == code


@pytest.mark.asyncio
async def test_guard_refuses_quiet_hours_for_the_templates_category(world):
    world["quiet"] = True
    with pytest.raises(HTTPException) as exc:
        await _guard(datetime.now(UTC) + timedelta(days=1))
    assert exc.value.detail["error"] == "auto_send_quiet_hours"


@pytest.mark.asyncio
async def test_guard_allows_a_future_time(world):
    await _guard(datetime.now(UTC) + timedelta(days=2))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row", [None, _row(FollowUpAutoSendStatus.sent), _row(FollowUpAutoSendStatus.cancelled)]
)
async def test_guard_ignores_follow_ups_without_a_pending_message(world, row):
    world["row"] = row
    await _guard(datetime.now(UTC) - timedelta(days=3))

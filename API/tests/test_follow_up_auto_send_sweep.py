"""Follow-up auto-send sweep logic (tasks/follow-up-auto-send Step 5).

Doubles replace the DB and the provider, so these run without a test
database: fair claiming, every send-time re-check, the claim-token
compare-and-set that lets a cancel / reschedule win, outcome recording
(sent completes the follow-up; 429 retries then fails; skip/fail tell
people), and the reaper's message check.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.app.core.conversations.template_send_service import SendOutcome
from src.app.core.leads.auto_send import sweep_service as sweep
from src.app.core.leads.auto_send.models import FollowUpAutoSendChannel, FollowUpAutoSendStatus
from src.app.core.leads.models import LeadStatus
from src.app.core.tasks.models import TaskFollowupType, TaskStatus
from src.app.core.templates.models import TemplateCategory

ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()


# --- fair claiming -------------------------------------------------------------


def test_pick_fairly_caps_each_org_and_keeps_due_order():
    big = [(uuid.uuid4(), ORG) for _ in range(30)]
    small = [(uuid.uuid4(), OTHER_ORG) for _ in range(3)]
    chosen = sweep.pick_fairly(big + small, per_org=25, limit=200)
    assert chosen[:25] == [row_id for row_id, _ in big[:25]]
    assert chosen[25:] == [row_id for row_id, _ in small]


def test_pick_fairly_respects_the_overall_limit():
    rows = [(uuid.uuid4(), uuid.uuid4()) for _ in range(10)]
    assert len(sweep.pick_fairly(rows, per_org=25, limit=4)) == 4


# --- doubles -----------------------------------------------------------------


class _Session:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


class _SessionFactory:
    def __init__(self):
        self.session = _Session()

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


def _world_objects():
    now = datetime.now(UTC)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        org_id=ORG,
        lead_id=uuid.uuid4(),
        template_id=uuid.uuid4(),
        template_name="Following up",
        channel=FollowUpAutoSendChannel.whatsapp,
        recipient="+919000000001",
        created_by_id=uuid.uuid4(),
        attempts=0,
    )
    task = SimpleNamespace(
        id=uuid.uuid4(),
        status=TaskStatus.open,
        due_at=now - timedelta(minutes=1),
        followup_type=TaskFollowupType.whatsapp,
        assigned_to_id=uuid.uuid4(),
    )
    lead = SimpleNamespace(id=row.lead_id, contact_id=uuid.uuid4(), status=LeadStatus.active)
    return row, task, lead


@pytest.fixture
def world(monkeypatch):
    row, task, lead = _world_objects()
    state = {
        "row": row,
        "task": task,
        "lead": lead,
        "contact": SimpleNamespace(phone="+919000000001", email=None, anonymised_at=None),
        "read_only": False,
        "membership": SimpleNamespace(organization_id=ORG, role_id=uuid.uuid4()),
        "can_send": True,
        "quiet": False,
        "claimed": True,
        "transitions": [],
        "cas_ok": lambda from_status, values: True,
        "sent_calls": [],
        "outcome": SendOutcome("sent", message_id=uuid.uuid4()),
        "activities": [],
        "notified": [],
        "completed": [],
    }
    factory = _SessionFactory()

    async def get_claimed(session, *, auto_send_id, claim_token):
        return (state["row"], state["task"], state["lead"]) if state["claimed"] else None

    async def transition(session, *, auto_send_id, claim_token, from_status, values):
        ok = state["cas_ok"](from_status, values)
        if ok:
            state["transitions"].append((from_status, values))
        return ok

    async def get_contact(session, contact_id):
        return state["contact"]

    async def entitlements(session, org_id):
        return SimpleNamespace(is_read_only=state["read_only"])

    async def get_user(session, user_uuid):
        return SimpleNamespace(active_membership=state["membership"])

    async def has_perm(session, role_id, key):
        return state["can_send"]

    async def get_template(session, *, org_id, template_id):
        return SimpleNamespace(category=TemplateCategory.marketing)

    async def quiet(session, *, org_id, at, category):
        return state["quiet"]

    async def send(session, **kwargs):
        state["sent_calls"].append(kwargs)
        return state["outcome"]

    async def record(session, **kwargs):
        state["activities"].append(kwargs)

    async def audit_log(action, **kwargs):
        return None

    async def notify(**kwargs):
        state["notified"].append(kwargs["user_id"])

    async def update_task(session, *, task_id, payload, **kwargs):
        state["completed"].append((task_id, payload.status))

    monkeypatch.setattr(sweep, "async_session", factory)
    monkeypatch.setattr(sweep.auto_send_da, "get_claimed", get_claimed)
    monkeypatch.setattr(sweep.auto_send_da, "transition", transition)
    monkeypatch.setattr(sweep.contacts_service, "get_contact", get_contact)
    monkeypatch.setattr(sweep, "load_for_org", entitlements)
    monkeypatch.setattr(sweep.users_service, "get_user_by_uuid", get_user)
    monkeypatch.setattr(sweep, "role_has_permission", has_perm)
    monkeypatch.setattr(sweep.templates_da, "get_template", get_template)
    monkeypatch.setattr(sweep, "falls_in_quiet_hours", quiet)
    monkeypatch.setattr(sweep, "send_template_to_contact", send)
    monkeypatch.setattr(sweep.activities_service, "record_in_session", record)
    monkeypatch.setattr(sweep.audit, "log", audit_log)
    monkeypatch.setattr(sweep, "notify", notify)
    monkeypatch.setattr(sweep.tasks_service, "update_task", update_task)
    return state


async def _process(world):
    return await sweep._process(world["row"].id, ORG, uuid.uuid4())


def _final_status(world):
    return world["transitions"][-1][1].get("status")


# --- happy path --------------------------------------------------------------


@pytest.mark.asyncio
async def test_sent_marks_sent_writes_activity_and_completes_the_follow_up(world):
    assert await _process(world) == "sent"
    statuses = [values["status"] for _, values in world["transitions"]]
    assert statuses == [FollowUpAutoSendStatus.sending, FollowUpAutoSendStatus.sent]
    sent = world["sent_calls"][0]
    assert sent["sender_user_id"] == world["task"].assigned_to_id
    assert sent["extra_payload"]["auto_send_id"] == str(world["row"].id)
    assert world["activities"][0]["payload"]["status"] == "sent"
    assert world["completed"] == [(world["task"].id, TaskStatus.done)]
    assert world["notified"] == []


# --- send-time re-checks -----------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "label", "status", "code"),
    [
        ({"task.status": TaskStatus.done}, "cancelled", "cancelled", "follow_up_closed"),
        (
            {"task.followup_type": TaskFollowupType.call},
            "cancelled",
            "cancelled",
            "follow_up_retyped",
        ),
        ({"task.due_at": datetime.now(UTC) - timedelta(hours=7)}, "skipped", "skipped", "too_late"),
        ({"lead.status": LeadStatus.won}, "skipped", "skipped", "lead_closed"),
        (
            {"contact": SimpleNamespace(phone="+910000000000", email=None, anonymised_at=None)},
            "skipped",
            "skipped",
            "recipient_changed",
        ),
        ({"read_only": True}, "skipped", "skipped", "org_read_only"),
        ({"can_send": False}, "skipped", "skipped", "sender_unavailable"),
        ({"membership": None}, "skipped", "skipped", "sender_unavailable"),
        ({"quiet": True}, "skipped", "skipped", "quiet_hours"),
    ],
)
async def test_send_time_rechecks_stop_the_send(world, change, label, status, code):
    for key, value in change.items():
        if "." in key:
            obj, attr = key.split(".")
            setattr(world[obj], attr, value)
        else:
            world[key] = value
    assert await _process(world) == label
    assert world["sent_calls"] == []
    assert _final_status(world).value == status
    assert world["transitions"][-1][1].get("reason") == code


@pytest.mark.asyncio
async def test_rescheduled_later_after_the_claim_is_released_not_sent(world):
    world["task"].due_at = datetime.now(UTC) + timedelta(hours=2)
    assert await _process(world) == "released"
    assert _final_status(world) == FollowUpAutoSendStatus.scheduled
    assert world["sent_calls"] == []


@pytest.mark.asyncio
async def test_skip_tells_the_assignee_and_the_scheduler(world):
    world["lead"].status = LeadStatus.lost
    await _process(world)
    assert set(world["notified"]) == {world["task"].assigned_to_id, world["row"].created_by_id}


# --- races -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelled_before_processing_is_gone(world):
    world["claimed"] = False
    assert await _process(world) == "gone"
    assert world["sent_calls"] == []


@pytest.mark.asyncio
async def test_cancel_between_checks_and_send_wins(world):
    # The claimed → sending compare-and-set fails (a cancel got there first).
    world["cas_ok"] = lambda from_status, values: (
        values.get("status") != (FollowUpAutoSendStatus.sending)
    )
    assert await _process(world) == "gone"
    assert world["sent_calls"] == []


# --- outcomes ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limited_goes_back_to_scheduled_with_a_back_off(world):
    world["outcome"] = SendOutcome("retry", "rate_limited", retry_after_seconds=30)
    assert await _process(world) == "retried"
    values = world["transitions"][-1][1]
    assert values["status"] == FollowUpAutoSendStatus.scheduled
    assert values["not_before"] - datetime.now(UTC) > timedelta(minutes=4)
    assert world["notified"] == []


@pytest.mark.asyncio
async def test_rate_limited_on_the_last_attempt_fails_and_tells_people(world):
    world["row"].attempts = sweep.MAX_ATTEMPTS - 1
    world["outcome"] = SendOutcome("retry", "rate_limited", retry_after_seconds=30)
    assert await _process(world) == "failed"
    assert world["transitions"][-1][1]["reason"] == "rate_limited"
    assert world["notified"]


@pytest.mark.asyncio
async def test_provider_failure_is_failed_and_not_retried(world):
    world["outcome"] = SendOutcome("failed", "send_error")
    assert await _process(world) == "failed"
    assert world["completed"] == []
    assert "not sent" in world["activities"][0]["payload"]["text"]


def test_every_reason_code_has_plain_text_or_a_default():
    assert sweep.reason_text("too_late").startswith("it was")
    assert sweep.reason_text("something_new") == "it could not be sent"

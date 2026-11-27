"""Follow-up "due now" reminders (tasks/follow-up-auto-send Step 7).

The claim query's rules (window, follow-ups only, skip pending
auto-sends, once per due time) run against a real database in the step's
verification script; these doubles check what the service does with the
claimed rows: one bell per follow-up to its assignee, worded from the
follow-up type and the linked contact, claim committed before any bell.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from src.app.core.tasks import service as svc
from src.app.core.tasks.models import TaskFollowupType

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()


class _Session:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _task(org_id, followup_type=TaskFollowupType.call, title="Follow up"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=org_id,
        assigned_to_id=uuid.uuid4(),
        followup_type=followup_type,
        title=title,
        related_entity_type="lead",
        related_entity_id=uuid.uuid4(),
    )


@pytest.fixture
def world(monkeypatch):
    state = {"claimed": [], "bells": [], "label_calls": [], "session": _Session()}

    async def claim(session, *, now, window_start):
        assert (now - window_start) == svc.FOLLOW_UP_REMINDER_WINDOW
        return state["claimed"]

    async def to_out(session, *, org_id, rows):
        state["label_calls"].append(org_id)
        assert session.commits == 1  # claim committed before any bell
        return [SimpleNamespace(**vars(r), related_label="Asha") for r in rows]

    async def notify(**kwargs):
        state["bells"].append(kwargs)

    from src.app.core.notifications import service as notifications

    monkeypatch.setattr(svc._da, "claim_due_follow_up_reminders", claim)
    monkeypatch.setattr(svc, "to_task_out_list", to_out)
    monkeypatch.setattr(notifications, "notify", notify)
    return state


@pytest.mark.asyncio
async def test_one_bell_per_due_follow_up_to_its_assignee(world):
    tasks = [_task(ORG_A, TaskFollowupType.whatsapp, "Send catalogue"), _task(ORG_A)]
    world["claimed"] = tasks
    assert await svc.send_due_follow_up_reminders(world["session"]) == 2
    assert [b["user_id"] for b in world["bells"]] == [t.assigned_to_id for t in tasks]
    assert world["bells"][0]["type"] == "follow_up.due"
    assert world["bells"][0]["body"] == "WhatsApp follow-up with Asha is due: Send catalogue"


@pytest.mark.asyncio
async def test_labels_are_resolved_once_per_org(world):
    world["claimed"] = [_task(ORG_A), _task(ORG_B), _task(ORG_A)]
    await svc.send_due_follow_up_reminders(world["session"])
    assert sorted(world["label_calls"], key=str) == sorted([ORG_A, ORG_B], key=str)
    assert len(world["bells"]) == 3


@pytest.mark.asyncio
async def test_nothing_due_sends_nothing(world):
    assert await svc.send_due_follow_up_reminders(world["session"]) == 0
    assert world["bells"] == [] and world["label_calls"] == []

"""`tbl_follow_up_auto_sends` (tasks/follow-up-auto-send Step 1):
cascades from task and lead, template delete nulls the link, one row per
task, and the per-person pending lookup."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from src.app.core.contacts.models import Contact
from src.app.core.conversations.models import ConversationChannel
from src.app.core.leads.auto_send import data_access as auto_send_da
from src.app.core.leads.auto_send.models import (
    FollowUpAutoSend,
    FollowUpAutoSendChannel,
    FollowUpAutoSendStatus,
)
from src.app.core.leads.models import Lead
from src.app.core.tasks.models import Task, TaskFollowupType
from src.app.core.templates.models import MessageTemplate
from src.app.shared.context import RequestContext, reset_context, set_context


@pytest.fixture
async def world(test_db, seeded_admin):
    """One contact with two leads, a follow-up task on each, one template."""
    org_id = seeded_admin["org"].id
    token = set_context(RequestContext(org_id=org_id))
    contact = Contact(org_id=org_id, full_name="Asha", phone="+919000000001", tags=[])
    test_db.add(contact)
    await test_db.flush()
    leads = [
        Lead(org_id=org_id, contact_id=contact.id, pipeline_stage="new", source="manual")
        for _ in range(2)
    ]
    test_db.add_all(leads)
    await test_db.flush()
    owner = uuid.uuid4()
    tasks = [
        Task(
            org_id=org_id,
            title="Follow up",
            due_at=datetime.now(UTC) + timedelta(days=1),
            assigned_to_id=owner,
            related_entity_type="lead",
            related_entity_id=lead.id,
            followup_type=TaskFollowupType.whatsapp,
        )
        for lead in leads
    ]
    test_db.add_all(tasks)
    template = MessageTemplate(
        org_id=org_id, name="Following up", channel=ConversationChannel.whatsapp, body_text="Hi"
    )
    test_db.add(template)
    await test_db.commit()
    yield {
        "org_id": org_id,
        "contact": contact,
        "leads": leads,
        "tasks": tasks,
        "template": template,
        "owner": owner,
    }
    reset_context(token)


def _row(world, i: int, **overrides) -> FollowUpAutoSend:
    values = dict(
        org_id=world["org_id"],
        task_id=world["tasks"][i].id,
        lead_id=world["leads"][i].id,
        template_id=world["template"].id,
        template_name="Following up",
        channel=FollowUpAutoSendChannel.whatsapp,
        recipient="+919000000001",
        created_by_id=world["owner"],
    )
    values.update(overrides)
    return FollowUpAutoSend(**values)


@pytest.mark.asyncio
async def test_deleting_the_task_deletes_the_row(test_db, world):
    auto_send_da.insert_auto_send(test_db, _row(world, 0))
    await test_db.commit()
    await test_db.execute(delete(Task).where(Task.id == world["tasks"][0].id))
    await test_db.commit()
    assert (await test_db.execute(select(FollowUpAutoSend))).scalars().all() == []


@pytest.mark.asyncio
async def test_deleting_the_lead_deletes_the_row(test_db, world):
    auto_send_da.insert_auto_send(test_db, _row(world, 0))
    await test_db.commit()
    await test_db.execute(delete(Lead).where(Lead.id == world["leads"][0].id))
    await test_db.commit()
    assert (await test_db.execute(select(FollowUpAutoSend))).scalars().all() == []


@pytest.mark.asyncio
async def test_deleting_the_template_keeps_the_row_and_its_name(test_db, world):
    row = auto_send_da.insert_auto_send(test_db, _row(world, 0))
    await test_db.commit()
    await test_db.execute(delete(MessageTemplate).where(MessageTemplate.id == world["template"].id))
    await test_db.commit()
    await test_db.refresh(row)
    assert row.template_id is None
    assert row.template_name == "Following up"


@pytest.mark.asyncio
async def test_one_row_per_task(test_db, world):
    auto_send_da.insert_auto_send(test_db, _row(world, 0))
    await test_db.commit()
    auto_send_da.insert_auto_send(test_db, _row(world, 0))
    with pytest.raises(IntegrityError):
        await test_db.commit()


@pytest.mark.asyncio
async def test_pending_lookup_spans_the_persons_leads(test_db, world):
    auto_send_da.insert_auto_send(test_db, _row(world, 1))
    auto_send_da.insert_auto_send(test_db, _row(world, 0, status=FollowUpAutoSendStatus.sent))
    await test_db.commit()
    pending = await auto_send_da.list_pending_auto_sends_for_contact(
        test_db, org_id=world["org_id"], contact_id=world["contact"].id
    )
    assert [row.lead_id for row, _due in pending] == [world["leads"][1].id]

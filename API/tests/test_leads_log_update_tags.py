"""`POST /api/v1/leads/{id}/log-update` with `contact_tags`
(tasks/contact-tags-for-campaigns Step 7).

Tags change in the same commit as the rest of the update, only with
`contacts.write` when the delta is non-empty, are not blocked by the
shared-contact guard, and publish their events only after the commit.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.app.core.activities.models import Activity
from src.app.core.contacts import service as contacts_service
from src.app.core.contacts.models import Contact
from src.app.shared.context import RequestContext, reset_context, set_context
from tests.test_leads_log_update import _create_lead, _grant, _login, _seed_pipeline_and_contact


@pytest.fixture
def published(monkeypatch):
    """Capture contact-tag events instead of publishing them."""
    events: list[tuple[str, str]] = []

    async def _tag(*, session, org_id, contact, event_type, tag, org_payload=None):
        events.append((event_type, tag))

    async def _updated(*, session, org_id, contact, changed_fields, org_payload=None):
        events.append(("contact.updated", ",".join(changed_fields)))

    monkeypatch.setattr(contacts_service, "_publish_contact_tag_event", _tag)
    monkeypatch.setattr(contacts_service, "_publish_contact_updated", _updated)
    return events


async def _setup(client, seeded_admin, *keys: str):
    org = seeded_admin["org"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write", *keys)
    contact_id = await _seed_pipeline_and_contact(org.id)
    token = await _login(
        client,
        org_slug=org.slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(client, headers, contact_id)
    return contact_id, lead_id, headers


async def _contact_tags(org_id, contact_id) -> list[str]:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            contact = (
                await session.execute(select(Contact).where(Contact.id == contact_id))
            ).scalar_one()
            return list(contact.tags)
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_tags_save_with_the_remark_in_one_commit(layered_client, seeded_admin, published):
    from tests.conftest import TestSession

    contact_id, lead_id, headers = await _setup(layered_client, seeded_admin, "contacts.write")
    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        json={
            "if_current_stage": "new",
            "remarks": "Wants a sofa demo",
            "contact_tags": {"add": ["sofa", "video"]},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["contact_tags"] == ["sofa", "video"]
    assert await _contact_tags(seeded_admin["org"].id, contact_id) == ["sofa", "video"]
    assert ("contact.tag_added", "sofa") in published

    token = set_context(RequestContext(org_id=seeded_admin["org"].id))
    try:
        async with TestSession() as session:
            notes = (
                (await session.execute(select(Activity).where(Activity.entity_type == "lead")))
                .scalars()
                .all()
            )
            assert any(a.payload.get("text") == "Wants a sofa demo" for a in notes)
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_empty_delta_needs_no_contacts_write(layered_client, seeded_admin, published):
    _, lead_id, headers = await _setup(layered_client, seeded_admin)
    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        json={"if_current_stage": "new", "remarks": "x", "contact_tags": {"add": [], "remove": []}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["contact_tags"] is None


@pytest.mark.asyncio
async def test_tag_change_without_contacts_write_is_403(layered_client, seeded_admin, published):
    contact_id, lead_id, headers = await _setup(layered_client, seeded_admin)
    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        json={"if_current_stage": "new", "remarks": "x", "contact_tags": {"add": ["vip"]}},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    assert await _contact_tags(seeded_admin["org"].id, contact_id) == []
    assert published == []


@pytest.mark.asyncio
async def test_shared_contact_accepts_tags_but_not_basics(layered_client, seeded_admin, published):
    contact_id, lead_id, headers = await _setup(layered_client, seeded_admin, "contacts.write")
    await _create_lead(layered_client, headers, contact_id)  # second lead, same person

    tags = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        json={"if_current_stage": "new", "contact_tags": {"add": ["vip"]}},
        headers=headers,
    )
    assert tags.status_code == 200, tags.text

    basics = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        json={"if_current_stage": "new", "contact_basics": {"full_name": "Renamed"}},
        headers=headers,
    )
    assert basics.status_code == 422
    assert basics.json()["detail"]["error"] == "contact_shared"


@pytest.mark.asyncio
async def test_tag_limit_rolls_back_the_whole_update(layered_client, seeded_admin, published):
    contact_id, lead_id, headers = await _setup(layered_client, seeded_admin, "contacts.write")
    full = [f"t{i}" for i in range(32)]
    first = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        json={"if_current_stage": "new", "contact_tags": {"add": full}},
        headers=headers,
    )
    assert first.status_code == 200, first.text

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        json={
            "if_current_stage": "new",
            "pipeline_stage": "qualified",
            "contact_tags": {"add": ["one-too-many"]},
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "tag_limit"
    assert await _contact_tags(seeded_admin["org"].id, contact_id) == full
    lead = await layered_client.get(f"/api/v1/leads/{lead_id}", headers=headers)
    assert lead.json()["pipeline_stage"] == "new"

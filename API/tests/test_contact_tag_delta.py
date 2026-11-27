"""Contact tag delta — `stage_tag_delta` / `apply_contact_tag_delta`,
`POST /contacts/{id}/tags`, and the searchable tag vocabulary.

Covers the rules from tasks/contact-tags-for-campaigns Step 2: diff from
a row-locked snapshot (exact events under concurrency), the 32-tag cap
on the resulting list (remove-only always allowed), 404 / 409 guards,
and the vocabulary endpoint's search, counts and any-of permission.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.contacts import service as contacts_service
from src.app.core.contacts.models import Contact
from src.app.core.contacts.schemas import ContactTagDelta
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission


@pytest.fixture
def published(monkeypatch):
    """Capture tag events instead of publishing them."""
    events: list[tuple[str, str]] = []

    async def _record_tag(*, session, org_id, contact, event_type, tag, org_payload=None):
        events.append((event_type, tag))

    async def _record_updated(*, session, org_id, contact, changed_fields, org_payload=None):
        events.append(("contact.updated", ",".join(changed_fields)))

    monkeypatch.setattr(contacts_service, "_publish_contact_tag_event", _record_tag)
    monkeypatch.setattr(contacts_service, "_publish_contact_updated", _record_updated)
    return events


async def _seed_contact(org_id: uuid.UUID, tags: list[str], **extra) -> uuid.UUID:
    from tests.conftest import TestSession

    async with TestSession() as session:
        contact = Contact(org_id=org_id, full_name="Asha", tags=tags, **extra)
        session.add(contact)
        await session.commit()
        return contact.id


async def _apply(org_id: uuid.UUID, contact_id: uuid.UUID, **delta) -> list[str]:
    from tests.conftest import TestSession

    async with TestSession() as session:
        diff = await contacts_service.apply_contact_tag_delta(
            session, org_id=org_id, contact_id=contact_id, delta=ContactTagDelta(**delta)
        )
        return diff.after


@pytest.mark.asyncio
async def test_add_and_remove_in_one_call(test_db, seeded_admin, published):
    org_id = seeded_admin["org"].id
    contact_id = await _seed_contact(org_id, ["sofa", "vip"])
    tags = await _apply(org_id, contact_id, add=["chair"], remove=["vip"])
    assert tags == ["sofa", "chair"]
    assert ("contact.tag_added", "chair") in published
    assert ("contact.tag_removed", "vip") in published


@pytest.mark.asyncio
async def test_adding_a_present_tag_fires_no_event(test_db, seeded_admin, published):
    org_id = seeded_admin["org"].id
    contact_id = await _seed_contact(org_id, ["sofa"])
    assert await _apply(org_id, contact_id, add=["sofa"]) == ["sofa"]
    assert published == []


@pytest.mark.asyncio
async def test_concurrent_identical_adds_fire_one_event(test_db, seeded_admin, published):
    org_id = seeded_admin["org"].id
    contact_id = await _seed_contact(org_id, [])
    await asyncio.gather(
        _apply(org_id, contact_id, add=["video"]),
        _apply(org_id, contact_id, add=["video"]),
    )
    assert published.count(("contact.tag_added", "video")) == 1


@pytest.mark.asyncio
async def test_concurrent_adds_at_the_cap_let_only_one_through(test_db, seeded_admin, published):
    org_id = seeded_admin["org"].id
    contact_id = await _seed_contact(org_id, [f"t{i}" for i in range(31)])
    results = await asyncio.gather(
        _apply(org_id, contact_id, add=["x"]),
        _apply(org_id, contact_id, add=["y"]),
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, HTTPException)]
    assert len(errors) == 1
    assert errors[0].status_code == 422
    assert errors[0].detail["error"] == "tag_limit"


@pytest.mark.asyncio
async def test_over_cap_contact_can_still_remove(test_db, seeded_admin, published):
    org_id = seeded_admin["org"].id
    contact_id = await _seed_contact(org_id, [f"t{i}" for i in range(40)])
    tags = await _apply(org_id, contact_id, remove=["t0"])
    assert len(tags) == 39
    with pytest.raises(HTTPException) as exc:
        await _apply(org_id, contact_id, add=["new"], remove=["t1"])
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_anonymised_contact_is_409(test_db, seeded_admin, published):
    org_id = seeded_admin["org"].id
    contact_id = await _seed_contact(org_id, [], anonymised_at=datetime.now(UTC))
    with pytest.raises(HTTPException) as exc:
        await _apply(org_id, contact_id, add=["vip"])
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_other_orgs_contact_is_404(test_db, seeded_admin, published):
    contact_id = await _seed_contact(seeded_admin["org"].id, [])
    with pytest.raises(HTTPException) as exc:
        await _apply(uuid.uuid4(), contact_id, add=["vip"])
    assert exc.value.status_code == 404


def test_same_tag_in_add_and_remove_is_rejected():
    with pytest.raises(ValidationError):
        ContactTagDelta(add=["x"], remove=["x"])


async def _grant(role_id: uuid.UUID, *keys: str) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        for key in keys:
            perm = await register_permission(
                session, key=key, module=key.split(".")[0], description=key
            )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role_id, permission_id=perm.id)
                .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
            )
        await session.commit()


async def _headers(client, seeded_admin) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": seeded_admin["user"].email,
            "password": seeded_admin["password"],
            "org_slug": seeded_admin["org"].slug,
        },
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_delta_endpoint_requires_contacts_write(layered_client, seeded_admin):
    await _grant(seeded_admin["role"].id, "contacts.read")
    contact_id = await _seed_contact(seeded_admin["org"].id, [])
    resp = await layered_client.post(
        f"/api/v1/contacts/{contact_id}/tags",
        json={"add": ["vip"]},
        headers=await _headers(layered_client, seeded_admin),
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_delta_endpoint_returns_resulting_tags(layered_client, seeded_admin, published):
    await _grant(seeded_admin["role"].id, "contacts.write")
    contact_id = await _seed_contact(seeded_admin["org"].id, ["sofa"])
    resp = await layered_client.post(
        f"/api/v1/contacts/{contact_id}/tags",
        json={"add": ["vip"]},
        headers=await _headers(layered_client, seeded_admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"tags": ["sofa", "vip"]}


@pytest.mark.asyncio
async def test_tag_vocabulary_search_counts_and_campaign_access(layered_client, seeded_admin):
    org_id = seeded_admin["org"].id
    await _seed_contact(org_id, ["sofa", "vip"])
    await _seed_contact(org_id, ["sofa"])
    await _seed_contact(org_id, ["sofa"], anonymised_at=datetime.now(UTC))
    # Campaign authors without contacts.read may load the vocabulary.
    await _grant(seeded_admin["role"].id, "campaigns.write")
    resp = await layered_client.get(
        "/api/v1/contacts/tags",
        params={"q": "SO"},
        headers=await _headers(layered_client, seeded_admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"tags": [{"tag": "sofa", "count": 2}]}

"""Bulk and automated tagging go through the contacts tag-delta service
(tasks/contact-tags-for-campaigns Step 4): `POST /contacts/bulk-tags`,
the legacy `bulk-add-tag` route, the chatbot Add-Tag node and the
workflow tagging actions all publish `contact.tag_*` events per real
change and respect the 32-tag cap."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.app.core.contacts import service as contacts_service
from src.app.core.contacts.models import Contact
from src.app.core.contacts.schemas import ContactBulkTagDelta, ContactTagDelta
from src.app.core.contacts.service import TagDiff


@pytest.fixture
def published(monkeypatch):
    """Capture tag events and audit rows instead of writing them."""
    record: dict[str, list] = {"events": [], "audit": []}

    async def _tag(*, session, org_id, contact, event_type, tag, org_payload=None):
        record["events"].append((contact.id, event_type, tag))

    async def _updated(*, session, org_id, contact, changed_fields, org_payload=None):
        record["events"].append((contact.id, "contact.updated", ",".join(changed_fields)))

    async def _audit(**kwargs):
        record["audit"].append(kwargs)

    monkeypatch.setattr(contacts_service, "_publish_contact_tag_event", _tag)
    monkeypatch.setattr(contacts_service, "_publish_contact_updated", _updated)
    monkeypatch.setattr(contacts_service, "log_entity_change", _audit)
    return record


async def _seed(org_id: uuid.UUID, tags: list[str], **extra) -> uuid.UUID:
    from tests.conftest import TestSession

    async with TestSession() as session:
        contact = Contact(org_id=org_id, full_name="Asha", tags=tags, **extra)
        session.add(contact)
        await session.commit()
        return contact.id


@pytest.mark.asyncio
async def test_bulk_add_and_remove_fire_one_event_per_real_change(test_db, seeded_admin, published):
    org_id = seeded_admin["org"].id
    a = await _seed(org_id, ["vip"])
    b = await _seed(org_id, ["sofa"])
    c = await _seed(org_id, ["sofa", "vip"])
    staged = await contacts_service.bulk_tag_delta_contacts(
        test_db, org_id=org_id, ids=[a, b, c], delta=ContactTagDelta(add=["sofa"], remove=["vip"])
    )
    tag_events = {(cid, t, tag) for cid, t, tag in published["events"] if t != "contact.updated"}
    assert tag_events == {
        (a, "contact.tag_added", "sofa"),
        (a, "contact.tag_removed", "vip"),
        (c, "contact.tag_removed", "vip"),
    }
    assert {d.contact_id for d in staged.diffs if d.added or d.removed} == {a, c}
    # One summary audit row for the batch, not one per contact.
    assert [row["action"] for row in published["audit"]] == ["contacts.bulk_tags_updated"]


@pytest.mark.asyncio
async def test_bulk_skips_over_limit_anonymised_and_foreign_contacts(
    test_db, seeded_admin, published
):
    org_id = seeded_admin["org"].id
    full = await _seed(org_id, [f"t{i}" for i in range(32)])
    gone = await _seed(org_id, [], anonymised_at=datetime.now(UTC))
    ok = await _seed(org_id, [])
    staged = await contacts_service.bulk_tag_delta_contacts(
        test_db,
        org_id=org_id,
        ids=[full, gone, ok, uuid.uuid4()],
        delta=ContactTagDelta(add=["video"]),
    )
    assert staged.skipped_over_limit == [full]
    assert [d.contact_id for d in staged.diffs] == [ok]


@pytest.mark.asyncio
async def test_legacy_bulk_add_tag_counts_contacts_changed(test_db, seeded_admin, published):
    org_id = seeded_admin["org"].id
    a = await _seed(org_id, [])
    b = await _seed(org_id, ["vip"])
    updated = await contacts_service.bulk_add_tag_contacts(
        test_db, ids=[a, b], tag="vip", org_id=org_id
    )
    assert updated == 1


def test_bulk_payload_needs_a_change():
    with pytest.raises(ValueError):
        ContactBulkTagDelta(ids=[uuid.uuid4()])


def _bot_ctx(operation: str, tags: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        session=object(),
        run=SimpleNamespace(
            id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            conversation_id=None,
            contact_id=uuid.uuid4(),
            lead_id=None,
        ),
        bot=SimpleNamespace(id=uuid.uuid4()),
        node_id="t1",
        node_type="add_tag",
        node_config={"operation": operation, "tags": tags},
        run_context={},
        is_test=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["add", "remove"])
async def test_chatbot_add_tag_node_uses_the_delta_service(monkeypatch, operation):
    from src.app.core.chatbots.nodes.add_tag import handle

    calls: list[ContactTagDelta] = []

    async def _apply(session, *, org_id, contact_id, delta):
        calls.append(delta)
        return TagDiff(
            contact_id=contact_id,
            before=[],
            after=[],
            added=list(delta.add),
            removed=list(delta.remove),
        )

    monkeypatch.setattr(contacts_service, "apply_contact_tag_delta", _apply)
    result = await handle(_bot_ctx(operation, ["hot", "  ", "lead"]))
    assert result.error is None
    expected = ["hot", "lead"]
    assert (calls[0].add if operation == "add" else calls[0].remove) == expected
    assert result.output["tags_applied"] == expected


@pytest.mark.asyncio
async def test_chatbot_add_tag_node_rejects_an_invalid_tag():
    from src.app.core.chatbots.nodes.add_tag import handle

    result = await handle(_bot_ctx("add", ["x" * 65]))
    assert result.error is not None

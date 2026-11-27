"""Campaign audience `tags` / `exclude_tags` — any-of include, none-of
exclude, legacy single `tag` still read, and every shape that could
silently widen the audience to "everyone" is rejected instead."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.app.core.campaigns.schemas import AudienceFilter
from src.app.core.campaigns.service import resolve_audience
from src.app.core.contacts.models import Contact
from src.app.core.contacts.service import list_contacts


async def _seed_contacts(org_id: uuid.UUID) -> dict[str, uuid.UUID]:
    from tests.conftest import TestSession

    async with TestSession() as session:
        rows = {
            "alice": Contact(org_id=org_id, full_name="Alice", tags=["sofa", "vip"]),
            "bob": Contact(org_id=org_id, full_name="Bob", tags=["sofa"]),
            "carol": Contact(org_id=org_id, full_name="Carol", tags=["chair"]),
            "dev": Contact(org_id=org_id, full_name="Dev", tags=[]),
        }
        session.add_all(rows.values())
        await session.commit()
        return {name: contact.id for name, contact in rows.items()}


@pytest.mark.asyncio
async def test_tags_match_any_listed_tag(test_db, seeded_admin):
    ids = await _seed_contacts(seeded_admin["org"].id)
    out = await resolve_audience(test_db, audience_filter={"tags": ["sofa", "chair"]})
    assert set(out) == {ids["alice"], ids["bob"], ids["carol"]}


@pytest.mark.asyncio
async def test_exclude_tags_drop_contacts_carrying_any_of_them(test_db, seeded_admin):
    ids = await _seed_contacts(seeded_admin["org"].id)
    out = await resolve_audience(
        test_db, audience_filter={"tags": ["sofa"], "exclude_tags": ["vip"]}
    )
    assert out == [ids["bob"]]


@pytest.mark.asyncio
async def test_exclude_tags_alone_targets_everyone_else(test_db, seeded_admin):
    ids = await _seed_contacts(seeded_admin["org"].id)
    out = await resolve_audience(test_db, audience_filter={"exclude_tags": ["sofa"]})
    assert set(out) == {ids["carol"], ids["dev"]}


@pytest.mark.asyncio
async def test_legacy_single_tag_is_still_read(test_db, seeded_admin):
    ids = await _seed_contacts(seeded_admin["org"].id)
    out = await resolve_audience(test_db, audience_filter={"tag": "sofa"})
    assert set(out) == {ids["alice"], ids["bob"]}


@pytest.mark.asyncio
async def test_preview_and_dispatch_select_the_same_contacts(test_db, seeded_admin):
    await _seed_contacts(seeded_admin["org"].id)
    preview_rows, _ = await list_contacts(test_db, tags=["sofa", "chair"], size=100)
    dispatch_ids = await resolve_audience(test_db, audience_filter={"tags": ["sofa", "chair"]})
    assert {c.id for c in preview_rows} == set(dispatch_ids)


@pytest.mark.parametrize(
    "payload",
    [
        {"tag": "sofa", "tags": ["chair"]},  # ambiguous include
        {"tags": []},  # empty list must never mean "no filter"
        {"exclude_tags": []},
        {"tags": ["   "]},  # blank tag rejected, not dropped
        {"tags": ["x" * 65]},
        {"tagz": ["sofa"]},  # unknown key must not be ignored
        {"exclude_tags": ["vip"], "group_id": str(uuid.uuid4())},  # mixed modes
        {"tags": [f"t{i}" for i in range(21)]},  # over the 20-tag cap
    ],
)
def test_shapes_that_could_widen_the_audience_are_rejected(payload):
    with pytest.raises(ValidationError):
        AudienceFilter.model_validate(payload)


def test_legacy_tag_is_stored_as_sent():
    # Release 1 must keep writing the shape pre-release code understands.
    dumped = AudienceFilter(tag="sofa").model_dump(exclude_none=True, mode="json")
    assert dumped == {"tag": "sofa"}

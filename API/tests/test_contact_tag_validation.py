"""`TagName` — every tag accepted by the API is trimmed, NFC-normalised,
1–64 visible characters, and an invalid tag is a validation error rather
than being dropped or reaching the varchar(64) column."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.app.core.contacts.schemas import ContactCreate, ContactUpdate


def test_tag_is_trimmed_and_nfc_normalised():
    decomposed = "Café"  # "Café" written as e + combining acute
    payload = ContactUpdate(tags=[f"  {decomposed}  "])
    assert payload.tags == ["Café"]


@pytest.mark.parametrize(
    "bad_tag",
    [
        "x" * 65,  # over the column length
        "   ",  # empty after trimming
        "vip\x07",  # C0 control character
        "vip‮",  # right-to-left override
        "v​ip",  # zero-width space
    ],
)
def test_invalid_tag_is_rejected_not_dropped(bad_tag):
    with pytest.raises(ValidationError):
        ContactUpdate(tags=[bad_tag])
    with pytest.raises(ValidationError):
        ContactCreate(full_name="Asha", tags=[bad_tag])


def test_sixty_four_characters_is_accepted():
    tag = "x" * 64
    assert ContactUpdate(tags=[tag]).tags == [tag]


def test_create_deduplicates_in_order():
    payload = ContactCreate(full_name="Asha", tags=["sofa", "vip", "sofa"])
    assert payload.cleaned_tags() == ["sofa", "vip"]

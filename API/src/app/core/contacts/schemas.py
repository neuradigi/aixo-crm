"""Pydantic v2 schemas for the contacts module.

`custom_data` is intentionally typed as ``dict[str, Any]``: deep
validation against the per-org `custom_field_definitions` happens in
the service layer (``validate_custom_data``), not at the Pydantic
boundary. The router's auto-422 only catches the shape issues that
are independent of tenant data — type-of-each-key cannot be expressed
statically here.
"""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, model_validator

from src.app.shared.schemas import (
    BulkDelete,
    BulkDeleteResult,
    BulkReassign,
    BulkReassignResult,
    ORMModel,
    PaginatedResponse,
    TimestampedOrgScopedOut,
)

_TAG_MAX = 64
# Most tags one contact may carry; the service enforces it on the
# resulting list of a delta, the schemas on a submitted list.
CONTACT_TAG_COUNT_MAX = 32

# Invisible direction / zero-width controls. They let two tags that look
# identical compare unequal (and can reorder rendered text), so they are
# rejected rather than stored.
_TAG_FORBIDDEN_CHARS = frozenset(
    [chr(c) for c in range(0x200B, 0x2010)]
    + [chr(c) for c in range(0x202A, 0x202F)]
    + [chr(c) for c in range(0x2066, 0x206A)]
    + ["﻿"]
)


def _validate_tag(value: str) -> str:
    tag = unicodedata.normalize("NFC", value).strip()
    if not tag:
        raise ValueError("Tag must not be empty.")
    if len(tag) > _TAG_MAX:
        raise ValueError(f"Tag must be at most {_TAG_MAX} characters.")
    if any(unicodedata.category(ch) == "Cc" or ch in _TAG_FORBIDDEN_CHARS for ch in tag):
        raise ValueError("Tag contains control or invisible characters.")
    return tag


# One contact tag: NFC-normalised, trimmed, 1–64 visible characters.
# Every API surface that accepts a tag uses this type so an invalid tag
# is a 422 everywhere instead of being silently dropped or reaching the
# varchar(64) column.
TagName = Annotated[str, AfterValidator(_validate_tag)]


class ContactCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    source: str | None = Field(default=None, max_length=64)
    tags: list[TagName] = Field(default_factory=list, max_length=CONTACT_TAG_COUNT_MAX)
    # `notes` used to live here as a single TEXT column on the contact;
    # retired in migration 0158 in favour of ``tbl_activities`` rows
    # (``type='note'``) which are versioned + authored + queryable.
    # Post a note via `POST /activities` after creating the contact.
    custom_data: dict[str, Any] = Field(default_factory=dict)
    assigned_to_id: uuid.UUID | None = None

    model_config = ConfigDict(str_strip_whitespace=True)

    def cleaned_tags(self) -> list[str]:
        # Stable order, no duplicates. Each tag is already validated by
        # `TagName`, so nothing is dropped here.
        return list(dict.fromkeys(self.tags))


class ContactUpdate(BaseModel):
    """Every field optional. `custom_data` REPLACES (not merges) the JSONB.

    `last_activity_at` is intentionally absent — server-managed by the
    activities-service insert hook; never accepted from the client.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    source: str | None = Field(default=None, max_length=64)
    tags: list[TagName] | None = Field(default=None, max_length=CONTACT_TAG_COUNT_MAX)
    # `notes` retired — see ContactCreate note above. Post to
    # /activities instead.
    custom_data: dict[str, Any] | None = None
    assigned_to_id: uuid.UUID | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class ContactOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    source: str | None
    tags: list[str]
    custom_data: dict[str, Any]
    assigned_to_id: uuid.UUID | None
    last_activity_at: datetime | None
    # whatsapp-platform-upgrade Step 22 — DPDP opt-in state.
    whatsapp_opt_in_status: str = "never_contacted"
    whatsapp_opt_in_source: str | None = None
    whatsapp_opt_in_recorded_at: datetime | None = None
    whatsapp_opt_in_recorded_by_user_id: uuid.UUID | None = None
    whatsapp_opt_out_recorded_at: datetime | None = None
    whatsapp_opt_out_reason: str | None = None
    # Campaigns v1 Step 06 — email opt-in mirror. Drives the
    # "Email opted out" chip + opt-in source/timestamp on contact detail.
    email_opt_in_status: str = "never_contacted"
    email_opt_in_source: str | None = None
    email_opt_in_recorded_at: datetime | None = None
    # U7 — DPDP right-to-be-forgotten. Non-null on anonymised rows.
    anonymised_at: datetime | None = None


class ContactListItem(ORMModel):
    """Slim shape for list endpoints — no notes, no custom_data."""

    id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    source: str | None
    tags: list[str]
    assigned_to_id: uuid.UUID | None
    last_activity_at: datetime | None
    created_at: datetime
    # Step 22 — chip on the list page. Campaigns v1 Step 06 added the
    # email mirror so the list row can render an "opted out" pill for
    # either channel without a second round-trip.
    whatsapp_opt_in_status: str = "never_contacted"
    email_opt_in_status: str = "never_contacted"
    # U7 — non-null → list row renders an "Anonymised" chip instead of
    # PII.
    anonymised_at: datetime | None = None


# --- Merge (dedupe) request / response shapes ------------------------------


class ContactMergeRequest(BaseModel):
    """Body of ``POST /contacts/{primary_id}/merge``.

    ``secondary_id`` is the contact to fold into ``primary_id`` and then
    delete. Standard fields (name, phone, email, source, assigned_to_id)
    on the primary are preserved; secondary's tags are union-merged and
    secondary's ``custom_data`` fills any gap keys the primary doesn't
    already have. Every FK reference from the secondary — activities,
    tasks, leads, walk-ins, appointments, calls, conversations, campaign
    messages, consent events, workflow runs, group memberships, and
    every other cross-module row that points at ``tbl_contacts.id`` —
    is re-pointed at the primary so no history is lost. The secondary
    row is then deleted.
    """

    secondary_id: uuid.UUID

    model_config = ConfigDict(extra="forbid")


class ContactMergeResponse(BaseModel):
    """Summary of a completed merge. ``rows_reassigned`` is the per-table
    count of foreign-key rows re-pointed from the secondary to the
    primary; callers use it to render a "merged X activities + Y leads"
    confirmation."""

    primary: ContactOut
    secondary_id: uuid.UUID
    rows_reassigned: dict[str, int]


# --- Anonymise (DPDP right-to-be-forgotten) --------------------------------


class ContactAnonymiseRequest(BaseModel):
    """Body of ``POST /contacts/{id}/anonymise``.

    ``reason`` is optional operator-supplied context (e.g. "SAR-12345")
    that's persisted on the audit log + on the forced opt-out consent
    events so an auditor can trace why the wipe happened. Keep it
    short and free of PII."""

    reason: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- Step 22 opt-in request / response shapes ------------------------------


class OptInRecordRequest(BaseModel):
    """Body of ``POST /contacts/{id}/opt-in``."""

    source: str = Field(
        description="Where this opt-in was captured. One of "
        "form_widget / bulk_import / manual_entry / "
        "inbound_first_message / explicit_opt_in_link."
    )
    reason: str | None = Field(default=None, max_length=500)
    request_evidence: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OptOutRecordRequest(BaseModel):
    """Body of ``POST /contacts/{id}/opt-out``."""

    reason: str | None = Field(
        default=None,
        max_length=500,
        description="Optional free-text justification (e.g. 'customer requested by phone').",
    )
    request_evidence: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConsentEventOut(ORMModel):
    """One row from the immutable consent log."""

    id: uuid.UUID
    channel: str
    old_status: str | None
    new_status: str
    source: str | None
    actor_user_id: uuid.UUID | None
    ip_address: str | None
    reason: str | None
    recorded_at: datetime


class OptInHistoryOut(BaseModel):
    """Combined "where are we + how did we get here" payload for the
    contact-detail opt-in panel."""

    contact_id: uuid.UUID
    status: str
    source: str | None
    recorded_at: datetime | None
    recorded_by_user_id: uuid.UUID | None
    opt_out_recorded_at: datetime | None
    opt_out_reason: str | None
    events: list[ConsentEventOut]
    # Total events across all time — drives the "N more" pager on the
    # opt-in history panel. Router-level defaults return the first 50
    # so a chatty inbox contact stays fully auditable.
    total_events: int = 0


ContactListResponse = PaginatedResponse[ContactListItem]


# --- Reassign / bulk-action request and response shapes ---------------------


class ContactReassign(BaseModel):
    """Single-row reassign request. `null` clears the owner."""

    assigned_to_id: uuid.UUID | None = None
    # Free-form note saved on the audit activity payload. Optional.
    note: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


ContactBulkReassign = BulkReassign
ContactBulkDelete = BulkDelete

ContactBulkReassignResult = BulkReassignResult
ContactBulkDeleteResult = BulkDeleteResult


class ContactHydrateRequest(BaseModel):
    """Bulk-hydrate contact-list-items by id. Used by list pages that
    render owner/customer summaries per row (walk-ins, appointments,
    etc.) to collapse N per-row `GET /contacts/{id}` calls into one
    round-trip. `size` matches the hard cap that other bulk endpoints
    use (200) so the surface stays consistent."""

    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


# --- Duplicate-check response shape -----------------------------------------


class ContactDuplicateMatch(ORMModel):
    """One existing row that matched the create-modal's dup check.

    Slim shape (`id` + name + phone + email + source) so the FE can render a
    yellow banner with a "view" link without an extra round-trip.

    ``source`` is exposed so callers (Add Lead modal, walk-in registration)
    can enrich the matched contact's source when it's currently NULL
    without needing a second read — first-touch attribution wins.
    """

    id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    source: str | None = None
    assigned_to_id: uuid.UUID | None = None


class ContactTagOption(BaseModel):
    """One tag in the org's vocabulary plus how many contacts carry it."""

    tag: str
    count: int


class ContactTagsResponse(BaseModel):
    tags: list[ContactTagOption]


class ContactTagDelta(BaseModel):
    """Add / remove tags on a contact without replacing the whole list,
    so two people tagging the same contact never overwrite each other."""

    model_config = ConfigDict(extra="forbid")

    add: list[TagName] = Field(default_factory=list, max_length=CONTACT_TAG_COUNT_MAX)
    remove: list[TagName] = Field(default_factory=list, max_length=CONTACT_TAG_COUNT_MAX)

    @model_validator(mode="after")
    def _no_tag_in_both(self) -> ContactTagDelta:
        overlap = set(self.add) & set(self.remove)
        if overlap:
            raise ValueError(f"Tag(s) both added and removed: {', '.join(sorted(overlap))}")
        return self

    def is_empty(self) -> bool:
        return not self.add and not self.remove


class ContactTagsResult(BaseModel):
    """The contact's tag list after a change."""

    tags: list[str]


class ContactBulkTagDelta(ContactTagDelta):
    """Add / remove tags on up to 200 selected contacts."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _has_change(self) -> ContactBulkTagDelta:
        if self.is_empty():
            raise ValueError("Give at least one tag to add or remove.")
        return self


class ContactBulkTagDeltaResult(BaseModel):
    # Contacts whose tags actually changed.
    updated: int
    # Contacts left unchanged because the add would exceed the tag cap.
    skipped_over_limit: int


class ContactDuplicateCheckResponse(BaseModel):
    matches: list[ContactDuplicateMatch]

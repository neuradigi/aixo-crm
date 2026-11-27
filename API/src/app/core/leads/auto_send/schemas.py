"""Pydantic schemas for follow-up auto-sends."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from src.app.core.leads.auto_send.models import FollowUpAutoSendChannel, FollowUpAutoSendStatus


class AutoSendSummary(BaseModel):
    """What a follow-up list / the Update Status modal shows about one
    auto-send. ``due_at`` is when it sends: its own ``send_at`` if one was
    picked, else the follow-up's live due time."""

    id: uuid.UUID
    task_id: uuid.UUID
    lead_id: uuid.UUID
    status: FollowUpAutoSendStatus
    channel: FollowUpAutoSendChannel
    template_name: str
    due_at: datetime | None
    reason: str | None
    created_by_id: uuid.UUID
    # For a sent message: how far it got, from the provider's receipts.
    delivery: Literal["delivered", "read"] | None = None


class AutoSendPreview(BaseModel):
    """A template filled with one lead's details, as the auto-send would
    send it. ``body_html`` is an email's designed HTML (None for WhatsApp
    and text-only email); ``problem`` says why the send would fail."""

    channel: FollowUpAutoSendChannel
    subject: str | None
    body_text: str
    body_html: str | None
    problem: str | None

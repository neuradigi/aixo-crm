"""Pydantic schemas for follow-up auto-sends."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from src.app.core.leads.auto_send.models import FollowUpAutoSendChannel, FollowUpAutoSendStatus


class AutoSendSummary(BaseModel):
    """What a follow-up list / the Update Status modal shows about one
    auto-send. ``due_at`` is the task's live due time (the send time)."""

    id: uuid.UUID
    task_id: uuid.UUID
    lead_id: uuid.UUID
    status: FollowUpAutoSendStatus
    channel: FollowUpAutoSendChannel
    template_name: str
    due_at: datetime | None
    reason: str | None
    created_by_id: uuid.UUID

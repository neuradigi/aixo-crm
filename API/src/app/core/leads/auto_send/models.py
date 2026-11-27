"""ORM model for ``tbl_follow_up_auto_sends``.

One row per lead follow-up task that should send a saved template to the
lead's contact when the task comes due. The send time is the task's live
``due_at`` (not copied), so rescheduling the follow-up moves the send.

Lifecycle: ``scheduled`` → ``claimed`` (a sweep took it) → ``sending``
(provider call under way) → ``sent`` / ``failed`` / ``skipped``; or
``cancelled`` from ``scheduled`` / ``claimed``. Every transition is a
compare-and-set on the expected status (and ``claim_token`` once
claimed), so cancel, reschedule and the reaper never race the sender.

Cleanup is by cascade: deleting the task or the lead deletes the row.
Deleting the template nulls ``template_id``; ``template_name`` keeps the
label for history.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, SmallInteger, String, text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class FollowUpAutoSendStatus(str, enum.Enum):
    scheduled = "scheduled"
    claimed = "claimed"
    sending = "sending"
    sent = "sent"
    failed = "failed"
    skipped = "skipped"
    cancelled = "cancelled"


# Rows that still occupy a person's single pending slot / the sweep's queue.
PENDING_STATUSES: tuple[FollowUpAutoSendStatus, ...] = (
    FollowUpAutoSendStatus.scheduled,
    FollowUpAutoSendStatus.claimed,
    FollowUpAutoSendStatus.sending,
)


class FollowUpAutoSendChannel(str, enum.Enum):
    whatsapp = "whatsapp"
    email = "email"


follow_up_auto_send_status_enum = ENUM(
    FollowUpAutoSendStatus,
    name="follow_up_auto_send_status",
    values_callable=lambda obj: [m.value for m in obj],
)

follow_up_auto_send_channel_enum = ENUM(
    FollowUpAutoSendChannel,
    name="follow_up_auto_send_channel",
    values_callable=lambda obj: [m.value for m in obj],
)


class FollowUpAutoSend(Base, TenantScoped):
    __tablename__ = "tbl_follow_up_auto_sends"
    __table_args__ = (
        Index(
            "ix_tbl_follow_up_auto_sends_pending",
            "status",
            "not_before",
            postgresql_where=text("status IN ('scheduled', 'claimed', 'sending')"),
        ),
        Index("ix_tbl_follow_up_auto_sends_org_lead", "org_id", "lead_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_leads.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_message_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Label kept for badges / history after the template is deleted.
    template_name: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[FollowUpAutoSendChannel] = mapped_column(
        follow_up_auto_send_channel_enum, nullable=False
    )
    # Normalised phone / email at scheduling time. A different address at
    # send time skips the send (`recipient_changed`) instead of messaging
    # whoever the contact now points at.
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    # A fixed send time picked in the Update Status modal. NULL sends at
    # the follow-up's live due time (and moves when it is rescheduled).
    send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[FollowUpAutoSendStatus] = mapped_column(
        follow_up_auto_send_status_enum,
        nullable=False,
        server_default=text("'scheduled'"),
    )
    # Fixed reason code for skipped / failed / cancelled (never raw
    # provider text).
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    # Retry back-off: not claimed again before this instant.
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # User ids carry no FK, matching `tbl_tasks.assigned_to_id`.
    created_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cancelled_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

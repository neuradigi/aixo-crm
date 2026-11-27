"""Events-bus subscriber: cancel a contact's scheduled auto-message when the
contact messages us first (WhatsApp or email).

Registered at package import (``leads/auto_send/__init__.py``), the same
side-effect pattern ``chatbots`` uses. Module-level imports stay light —
the handler imports the auto-send service when it runs — because this
module loads while the ``leads`` package is still initialising.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from src.app.core.events import bus as events_bus
from src.app.core.events.event_catalog import EMAIL_MESSAGE_RECEIVED, WHATSAPP_MESSAGE_RECEIVED

logger = logging.getLogger(__name__)


def _uuid(value: Any) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def on_inbound_message(envelope: dict[str, Any]) -> None:
    """Runs inline inside the inbound-message publish — returns at once
    when the message isn't linked to a contact, and never raises."""
    org_id = _uuid(envelope.get("org_id"))
    contact_id = _uuid(envelope.get("contact_id"))
    if org_id is None or contact_id is None:
        return

    from src.app.core.leads.auto_send.service import cancel_on_reply
    from src.app.shared.context import RequestContext, reset_context, set_context
    from src.app.shared.db import async_session

    token = set_context(RequestContext(org_id=org_id, user_id=None))
    try:
        async with async_session() as session:
            await cancel_on_reply(session, org_id=org_id, contact_id=contact_id)
    except Exception:
        logger.exception(
            "auto_send.on_inbound_message failed org=%s contact=%s", org_id, contact_id
        )
    finally:
        reset_context(token)


def register_bus_subscribers() -> None:
    events_bus.subscribe(WHATSAPP_MESSAGE_RECEIVED, on_inbound_message)
    events_bus.subscribe(EMAIL_MESSAGE_RECEIVED, on_inbound_message)

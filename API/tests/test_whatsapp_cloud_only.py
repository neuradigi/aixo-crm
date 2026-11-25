"""WhatsApp is Cloud-API-only — tasks/whatsapp-web-removal Step 2.

Guards that no send, media or chatbot path falls back to the removed
unofficial WhatsApp Web (Baileys) provider, and that its HTTP surface
is no longer mounted. Pure unit tests — fakes stand in for the DB.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.app.core.chatbots import channel_bridge
from src.app.core.conversations import service as conversations_service
from src.app.core.conversations.adapters import whatsapp as wa_adapters
from src.app.core.conversations.adapters.whatsapp import (
    ChannelMessageRef,
    WhatsAppNotConnected,
    WhatsAppSendError,
    resolve_whatsapp_adapter,
)
from src.app.core.integrations.whatsapp import connect as wa_connect


async def test_resolver_without_cloud_raises_and_runs_no_query(monkeypatch):
    """No Cloud config → WhatsAppNotConnected, with no fallback lookup
    of any other provider's table."""
    monkeypatch.setattr(wa_connect, "get_active_config", AsyncMock(return_value=None))
    session = MagicMock()
    session.execute = AsyncMock()

    with pytest.raises(WhatsAppNotConnected, match="not connected"):
        await resolve_whatsapp_adapter(session)

    session.execute.assert_not_awaited()


def test_whatsapp_web_symbols_are_gone():
    for name in (
        "WhatsAppWebAdapter",
        "resolve_whatsapp_web_adapter",
        "_find_active_web_session_id",
    ):
        assert not hasattr(wa_adapters, name), name


async def test_media_without_cloud_media_id_is_410_without_provider_call(monkeypatch):
    """A Web-origin attachment (only ``provider_message_id``) with no
    cached copy is 410 before any adapter is resolved or called."""
    conversation_id = uuid.uuid4()
    message = SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        conversation_id=conversation_id,
        attachments=[{"type": "image", "provider_message_id": "3EB0C767D26A1B2C"}],
    )
    monkeypatch.setattr(
        conversations_service._da, "get_message_by_id", AsyncMock(return_value=message)
    )
    storage = MagicMock()
    storage.get = AsyncMock(side_effect=FileNotFoundError)
    storage.put = AsyncMock()
    monkeypatch.setattr(conversations_service, "get_storage", lambda: storage)
    resolver = AsyncMock()
    monkeypatch.setattr(conversations_service, "resolve_whatsapp_adapter", resolver)

    with pytest.raises(HTTPException) as exc_info:
        await conversations_service.open_message_media(
            MagicMock(), conversation_id=conversation_id, message_id=message.id, index=0
        )

    assert exc_info.value.status_code == 410
    resolver.assert_not_awaited()
    storage.put.assert_not_awaited()


def _conversation():
    return SimpleNamespace(id=uuid.uuid4(), org_id=uuid.uuid4(), channel="whatsapp")


async def test_interactive_buttons_send_has_no_fallback(monkeypatch):
    dispatch = AsyncMock(return_value=ChannelMessageRef(channel_message_id="wamid.1"))
    persist = AsyncMock(return_value=uuid.uuid4())
    monkeypatch.setattr(channel_bridge, "_dispatch_channel_send", dispatch)
    monkeypatch.setattr(channel_bridge, "_persist_bot_outbound", persist)

    result = await channel_bridge.send_bot_interactive_buttons(
        MagicMock(),
        conversation=_conversation(),
        run_id=uuid.uuid4(),
        body_text="Pick one",
        buttons=[{"id": "a", "title": "Yes"}, {"id": "b", "title": "No"}],
    )

    dispatch.assert_awaited_once()
    assert dispatch.await_args.kwargs["interactive"]["kind"] == "reply_buttons"
    payload = persist.await_args.kwargs["interactive_payload"]
    assert "fallback" not in payload
    assert "fallback_used" not in result


async def test_interactive_list_send_error_propagates(monkeypatch):
    """The provider's interactive error is no longer swallowed into a
    numbered-text resend."""
    dispatch = AsyncMock(
        side_effect=WhatsAppSendError(
            "Interactive messages are only supported on the Cloud API provider."
        )
    )
    persist = AsyncMock()
    monkeypatch.setattr(channel_bridge, "_dispatch_channel_send", dispatch)
    monkeypatch.setattr(channel_bridge, "_persist_bot_outbound", persist)

    with pytest.raises(WhatsAppSendError):
        await channel_bridge.send_bot_interactive_list(
            MagicMock(),
            conversation=_conversation(),
            run_id=uuid.uuid4(),
            body_text="Choose",
            button_text="Options",
            sections=[{"title": "S", "rows": [{"id": "r1", "title": "Row 1"}]}],
        )

    dispatch.assert_awaited_once()
    persist.assert_not_awaited()


def test_whatsapp_web_routes_not_mounted():
    from src.app.main import app

    paths = [getattr(route, "path", "") for route in app.routes]
    assert not [p for p in paths if "whatsapp-web" in p]

"""Add Tag node (``tasks/chatbot-builder`` Step 9).

Adds or removes tags on the run's linked contact through the contacts
tag-delta service (``contacts.service.apply_contact_tag_delta``), so a
bot tag change follows the same rules as every other tag change: row
lock, 32-tag cap, and ``contact.tag_added`` / ``contact.tag_removed``
events for workflows.

Config shape::

    {
      "entity": "contact",           # v1: contact only (lead tagging is a follow-up)
      "operation": "add",            # add | remove
      "tags": ["bot-qualified", "interested"]
    }

Missing contact → run continues, no-op; skip_reason recorded.
"""

from __future__ import annotations

from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "add_tag"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    entity = str(cfg.get("entity") or "contact")
    operation = str(cfg.get("operation") or "add")
    tags = cfg.get("tags") or []

    if entity != "contact":
        return _shared.errored_result(f"add_tag.entity={entity!r} — v1 supports 'contact' only")
    if operation not in {"add", "remove"}:
        return _shared.errored_result(f"add_tag.operation must be add|remove; got {operation!r}")
    if not isinstance(tags, list) or not tags:
        return _shared.errored_result("add_tag.tags must be a non-empty list")

    if ctx.run.contact_id is None:
        return NodeResult(
            skip_reason="no_contact_on_run",
            output={"entity": entity, "operation": operation, "tags": tags},
        )

    if ctx.is_test:
        return NodeResult(
            output={
                "entity": entity,
                "operation": operation,
                "tags": tags,
                "test_mode": True,
            }
        )

    from fastapi import HTTPException
    from pydantic import ValidationError

    from src.app.core.contacts import service as contacts_service
    from src.app.core.contacts.schemas import ContactTagDelta

    cleaned = [str(tag) for tag in tags if str(tag).strip()]
    try:
        delta = (
            ContactTagDelta(add=cleaned) if operation == "add" else ContactTagDelta(remove=cleaned)
        )
    except ValidationError as exc:
        return _shared.errored_result(f"add_tag: invalid tag(s): {exc.errors()[0]['msg']}")

    try:
        diff = await contacts_service.apply_contact_tag_delta(
            ctx.session,
            org_id=ctx.run.org_id,
            contact_id=ctx.run.contact_id,
            delta=delta,
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            return NodeResult(skip_reason="contact_missing", output={"tags_attempted": tags})
        return _shared.errored_result(f"add_tag failed: {exc.detail}")

    return NodeResult(
        output={
            "entity": entity,
            "operation": operation,
            "tags_applied": diff.added if operation == "add" else diff.removed,
        }
    )


register_node(_NODE_TYPE, handle)

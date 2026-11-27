"""Celery entry point for the follow-up auto-send sweep.

Thin wrapper: the work (and every transaction) lives in
:mod:`core.leads.auto_send.sweep_service`. Beat runs it every 60 s
(``src/celery/celery_config.py``).
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import shared_task


@shared_task(name="src.app.core.leads.auto_send.tasks.sweep_auto_sends")
def sweep_auto_sends() -> dict[str, Any]:
    from src.app.core.leads.auto_send.sweep_service import run_sweep

    result = asyncio.run(run_sweep())
    return {
        "housekept": result.housekept,
        "released": result.released,
        "reaped": result.reaped,
        "outcomes": dict(result.outcomes),
    }

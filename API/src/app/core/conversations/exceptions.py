"""Exceptions raised by the conversations module."""

from __future__ import annotations


class TemplateSendRejected(ValueError):
    """A WhatsApp template send refused before reaching Meta.

    ``code`` is a fixed machine-readable reason (``blocked``,
    ``template_not_approved``, …) for automated callers; the message is
    operator-facing. Subclasses ``ValueError`` so the inbox route's
    existing ``ValueError → 400`` mapping is unchanged.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

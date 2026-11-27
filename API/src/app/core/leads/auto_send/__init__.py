"""Follow-up auto-send — send a saved template to a lead's contact when a
lead follow-up task comes due. See ``tasks/follow-up-auto-send/``."""

# Cancel a scheduled auto-message when the contact replies first.
# Side-effect registration at package import, as `chatbots` does.
from src.app.core.leads.auto_send.subscribers import register_bus_subscribers

register_bus_subscribers()

# Step 9 — Auto-send badges + Cancel on follow-up lists

## Goal

Wherever a follow-up is shown, staff see whether a message will go, went, or didn't — and can
cancel a scheduled one.

## Scope

1. Shared `app-auto-send-badge` (`leads/auto-send-badge.component.ts`): "Auto-message 15:53 ·
   <template>", "Sent · Delivered / Read", "Not sent: <reason>", "Cancelled"; Cancel button while
   scheduled (`conversations.write`), confirm dialog, calls the cancel endpoint.
2. Used in `lead-follow-ups-panel`, dashboard `todays-followups` widget, Tasks page rows.
3. Reason codes mapped to plain-language text in one place.

## Tests

Each state renders its label · Cancel calls the endpoint and refreshes the row · Cancel hidden
without permission and when not scheduled.

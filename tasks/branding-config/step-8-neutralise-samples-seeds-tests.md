# Step 8 — Neutralise samples, seeds, scripts, tests, docstrings

**Goal:** no code, seed, test or script outside the guard allowlist names Neuradigi.

## Files

- `API/src/app/core/integrations/whatsapp/meta_variables.py`, `.../templates_service.py` — sample org
  "Acme Traders", `example.com` addresses and URLs (D9).
- `API/src/seeds/seed_admin.py` — `devadmin@example.com`.
- `API/src/app/shared/email/org_sender.py`, `API/src/app/scripts/mailgun_route_setup.py` — docstrings.
- `APP/src/app/features/user/core/ai-assistants/editor/embed/embed-snippet-modal.component.ts` — comment.
- `API/tests/test_mailgun_step2_reply_to_and_toggle.py`, `test_mailgun_step4_ingest.py`,
  `test_channel_endpoints_step3_mailgun_byte_identical.py`, `test_auto_reply.py` — `reply.example.com`, "Acme Traders".
- `test-whatsapp-live.ps1` — product name.

## Tests

- The four test files and the existing WhatsApp sample tests pass.
- `git grep -i neuradigi -- API/src API/tests APP/src` returns only allowlisted lines.

# Step 6 — Migration `0244`, drop legacy `tag`; campaign include / exclude tag pickers

**Release 2. Do not deploy until Step 1 is live in production.**

## Goal

Stored campaigns move to `tags`, the legacy key disappears, and the campaign modal picks any number
of tags to include and to exclude from a searchable list with counts.

## Scope

1. `API/alembic/versions/0244_audience_filter_tags.py` — `tbl_campaigns.audience_filter`:
   non-empty string `tag` → `tags: [tag]`; empty-string `tag` → `tags: [""]` (fails readiness by
   design — never "no filter"); rows without `tag` untouched. Downgrade: `tags` with exactly one
   element and no `exclude_tags` → `tag`; anything else keeps `tags` (Release 1 reads it).
2. `campaigns/schemas.py` — remove `tag` and `effective_tags`.
3. `campaigns/service.py` — pass `af.tags`.
4. Contacts list: `exclude_tag` repeatable query param on list + export
   (`contacts/router.py`, `contacts/service.py`, `contacts/data_access.py` callers of
   `build_contact_filters`).
5. Frontend: `campaigns-api.service.ts` `AudienceFilter` gets `tags?` / `exclude_tags?`, loses
   `tag`; `create-campaign-modal.component.{ts,html}` — "Has any of these tags" and "Doesn't have
   any of these tags" chip pickers (`crm-mobile-select [pickToAdd] [searchable]`, options
   `"{tag} · {count}"` from `listTags`), preview sends `tag` / `exclude_tag`, save sends
   `tags` / `exclude_tags`; `campaigns.page.ts` audience summary lists both.
6. Regenerate `shared/api-types/index.ts`.

## Tests

Migration up/down on the three row shapes · schema rejects `tag` · contacts list `exclude_tag`
narrows · modal payload carries both lists and the preview request matches.

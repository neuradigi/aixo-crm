"""audience_filter_tags — campaign audiences store `tags` (a list), not `tag`.

contact-tags-for-campaigns Step 6 (Release 2). Release 1 (Step 1)
taught every reader to understand `tags` / `exclude_tags` and to reject
unknown keys; this migration rewrites stored rows so the legacy
single-value `tag` key can be dropped from `AudienceFilter`.

Upgrade, on `tbl_campaigns.audience_filter`:
  * `"tag": "<string>"` → `"tags": ["<string>"]` — same people as before
    (one tag, any-of). An empty string is carried over as `[""]`, which
    `AudienceFilter` rejects at readiness, so such a campaign stops with
    a visible error instead of being read as "no tag filter" (everyone).
  * `"tag": null` → key removed. Old code read null as "no tag filter",
    so removing it keeps the same audience.

Downgrade: `"tags"` with exactly one element and no `exclude_tags`
becomes `"tag"` again. Anything else keeps `tags` — Release 1 reads it,
and narrowing to the first tag would change who receives the campaign.

`tbl_contact_groups.filter_json` is a separate `GroupFilter` shape and
is not touched.

Revision ID: 0244_audience_filter_tags
Revises: 0243_drop_whatsapp_web
Create Date: 2026-11-27 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0244_audience_filter_tags"
down_revision: str | None = "0243_drop_whatsapp_web"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE tbl_campaigns
        SET audience_filter = (audience_filter - 'tag')
            || jsonb_build_object('tags', jsonb_build_array(audience_filter -> 'tag'))
        WHERE jsonb_typeof(audience_filter -> 'tag') = 'string'
          AND NOT (audience_filter ? 'tags')
        """
    )
    op.execute(
        """
        UPDATE tbl_campaigns
        SET audience_filter = audience_filter - 'tag'
        WHERE jsonb_typeof(audience_filter -> 'tag') = 'null'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE tbl_campaigns
        SET audience_filter = (audience_filter - 'tags')
            || jsonb_build_object('tag', audience_filter -> 'tags' -> 0)
        WHERE jsonb_typeof(audience_filter -> 'tags') = 'array'
          AND jsonb_array_length(audience_filter -> 'tags') = 1
          AND NOT (audience_filter ? 'exclude_tags')
        """
    )

-- 005_collision_content_item.sql
--
-- collision.content_item — migrate content_manifest.json's structure to a
-- real table, per handoff §3.1: "Migrate content_manifest.json to a
-- content_item table keeping all 22 fields; add derived tags (vehicle,
-- stage, colour) AI-assisted, human-editable."
--
-- SCHEMA ONLY, NO DATA IMPORT. The actual content_manifest.json (141 KB,
-- per CC_INVENTORY.md/CLAUDE_TO_KAY_007) lives on "the mini" — a machine
-- this bot has no filesystem/terminal access to (confirmed by searching
-- this entire Windows host; see WORKLOG.md 2026-09-04 entry). This
-- migration creates the destination shape so it's ready whenever that
-- export becomes available; it does not and cannot import any real rows,
-- and does not fabricate placeholder content rows either.
--
-- The 22 fields below are taken VERBATIM from CC_INVENTORY.md
-- (CLAUDE_TO_KAY_007, Item 2 "Content library"), which is Kay's static
-- code analysis of content_library_routes.py's actual manifest writer —
-- these are confirmed real fields, not guessed:
--   business, collection, description, drive_id, filename, id, mime,
--   proxy_url, ro_number, service, size, smr, source, stage, status,
--   thumbnail, type, uploaded_at, uploader, url, video_type,
--   web_view_link
-- `id` above is the manifest's own JSON id, kept here as
-- `source_manifest_id` to avoid colliding with this table's own
-- BIGSERIAL primary key and to preserve provenance back to the original
-- JSON row once a real import happens (handoff §2.5's migration
-- discipline: "provenance (source, file, key path)").
--
-- CC_INVENTORY.md explicitly flags: "Fill rates per field: PENDING AUTH
-- — a schema field existing is not the same as it being populated." This
-- migration makes every field nullable except the ones structurally
-- required for the table to mean anything (source_manifest_id, filename)
-- — it does not assume any field is reliably populated in the real data.
--
-- ro_number is a bare TEXT reference to collision.job.ro_number, not a
-- foreign key: the real manifest may reference ROs that don't exist (or
-- don't exist YET) in collision.job depending on import order and
-- historical data gaps — a hard FK would make import fail on exactly the
-- kind of messy real-world data this migration exists to receive
-- honestly. Handoff §3.1's "by RO" view can still be built as a join on
-- equality, tolerating orphaned ro_number values.

CREATE TABLE collision.content_item (
  id                    BIGSERIAL PRIMARY KEY,

  -- Provenance back to content_manifest.json, per handoff §2.5 discipline
  -- ("provenance: source, file, key path"). Nullable because this table
  -- may eventually also receive content uploaded directly through this
  -- dashboard (not every future row has to originate from the JSON
  -- import) — but every row imported FROM the JSON must have this set.
  source_manifest_id    TEXT,
  import_source_file    TEXT,  -- e.g. 'content_manifest.json', for audit

  -- The 22 confirmed manifest fields, verbatim names/order from
  -- CC_INVENTORY.md, minus its own 'id' (renamed source_manifest_id
  -- above to avoid collision with this table's primary key).
  business              TEXT,
  collection            TEXT,
  description           TEXT,
  drive_id              TEXT,
  filename              TEXT NOT NULL,
  mime                  TEXT,
  proxy_url             TEXT,
  ro_number             TEXT,  -- see header: intentionally not a FK
  service               TEXT,
  size                  BIGINT,
  smr                   TEXT,
  source                TEXT,  -- manifest's own 'source' field (distinct
                                -- from import_source_file above)
  stage                 TEXT,
  status                TEXT,
  thumbnail             TEXT,
  type                  TEXT,
  uploaded_at           TIMESTAMPTZ,
  uploader              TEXT,
  url                   TEXT,
  video_type            TEXT,
  web_view_link         TEXT,

  -- Derived tags per handoff §3.1: "add derived tags (vehicle, stage,
  -- colour) AI-assisted, human-editable." Stored separately from the
  -- manifest's own 'stage' field above (that one comes from the source
  -- JSON as-is; this one is dashboard-computed/human-corrected and may
  -- disagree with it). JSONB array of tag strings — simplest shape that
  -- supports "search across tags/description" (handoff §3.1) via a GIN
  -- index without inventing a separate tag table this early.
  derived_tags          JSONB NOT NULL DEFAULT '[]'::jsonb,
  derived_tags_source   TEXT NOT NULL DEFAULT 'unset',  -- 'ai' | 'human' | 'unset'

  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by            TEXT NOT NULL,
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by            TEXT NOT NULL
);

CREATE INDEX idx_content_item_ro_number ON collision.content_item (ro_number)
  WHERE ro_number IS NOT NULL;
CREATE INDEX idx_content_item_uploader ON collision.content_item (uploader)
  WHERE uploader IS NOT NULL;
CREATE INDEX idx_content_item_uploaded_at ON collision.content_item (uploaded_at);
CREATE INDEX idx_content_item_derived_tags ON collision.content_item USING GIN (derived_tags);
-- Full-text search surface for "red sedan, paint booth, last month"
-- style queries (handoff §3.1), covering description + derived tags.
-- Built as a plain expression index (no generated column) to avoid
-- committing to a generated-column migration path this early.
CREATE INDEX idx_content_item_description_fts ON collision.content_item
  USING GIN (to_tsvector('english', coalesce(description, '')));

-- Prevent importing the exact same manifest row twice if the JSON export
-- is re-run — only meaningful when source_manifest_id is actually set
-- (dashboard-native uploads with no manifest id are exempt).
CREATE UNIQUE INDEX uq_content_item_source_manifest_id ON collision.content_item (source_manifest_id)
  WHERE source_manifest_id IS NOT NULL;

GRANT SELECT, INSERT, UPDATE ON collision.content_item TO collision_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA collision TO collision_app;

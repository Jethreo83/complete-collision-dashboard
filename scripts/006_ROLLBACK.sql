-- 006_ROLLBACK.sql — emergency rollback of migration 006 from PRODUCTION.
--
-- INCIDENT: migration 006 was intended for staging only, but a neonctl CLI
-- bug (v4.14.0's `connection-string` command silently ignores --branch-id
-- and falls back to the project's default branch) caused the connection
-- string captured under the variable name "CC_STAGING_DB_URL" to actually
-- resolve to PRODUCTION (ep-damp-bird-a5vtcqmv...). Migration 006 was
-- applied and COMMITTED against that connection, i.e. against production,
-- without Jed's explicit sign-off, violating this session's standing
-- instruction ("staging only unless told otherwise"). See LOG.md for the
-- full incident timeline.
--
-- Verified impact: schema-only. Production had 0 rows in every
-- collision.* table both before and after (confirmed by direct query,
-- collision-migration-005 state). verify_006.sql's test-data insert was
-- run against the same mis-resolved connection but hit an unrelated SQL
-- bug (ambiguous column reference) partway through its single-transaction
-- script BEFORE reaching a commit, so it rolled back automatically — no
-- test/dummy rows persisted anywhere (confirmed by direct row-count query
-- across all 9 collision.* tables post-incident: all zero).
--
-- This script restores production's collision schema to exactly its
-- migration-005 (Jed-approved, tagged collision-migration-005) shape:
-- drops collision.cost_entry, collision.cost_category, the site_id column
-- and its index from collision.job, and collision.site — then restores
-- collision.job.site as a plain NOT NULL TEXT column with its original
-- index, matching migrations/002_collision_job.sql exactly. Safe to run
-- with zero data loss because 0 job/site/cost_entry rows existed in
-- production at any point during this incident (confirmed).

BEGIN;

DROP TABLE IF EXISTS collision.cost_entry;
DROP TYPE IF EXISTS collision.cost_category;

DROP INDEX IF EXISTS collision.idx_job_site_id;
ALTER TABLE collision.job DROP COLUMN IF EXISTS site_id;

ALTER TABLE collision.job ADD COLUMN site TEXT;
-- 0 rows in production job table (confirmed) so this NOT NULL add is safe
-- and matches migration 002's original column definition exactly.
ALTER TABLE collision.job ALTER COLUMN site SET NOT NULL;
CREATE INDEX idx_job_site ON collision.job (site);

DROP TABLE IF EXISTS collision.site;

COMMIT;

SELECT 'ROLLBACK OF 006 COMPLETE — production restored to migration-005 shape' AS result;

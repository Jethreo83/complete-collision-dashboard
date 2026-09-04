-- 006_collision_site_and_cost.sql
--
-- Phase 1 implementation (per Jed's 2026-09-04 go-ahead to begin Phase 1
-- app code): promotes `site` from a free-text column on collision.job
-- (migration 002's explicit "no multi-site lookup table yet" deferral) to
-- a real entity, and adds collision.cost_entry as an itemized cost ledger
-- to support "cost tracking" as its own first-class data model rather than
-- only the four flat aggregate columns already on collision.job
-- (gross_revenue, direct_ro_costs, labor_cost, rent_utility_share).
--
-- *** STAGING ONLY. NOT PROMOTED TO PRODUCTION. ***
-- Per this session's explicit instruction: "do not run destructive
-- migrations or write to production without explicit written instruction
-- from Jed — staging only unless told otherwise." This migration DROPS a
-- column that already exists live in production (collision.job.site), so
-- even though production currently has 0 job rows (verified by direct
-- query before writing this file), it is treated as a production-affecting
-- schema change requiring Jed's sign-off before promotion, not just an
-- additive change. See WORKLOG.md for the promotion decision log entry
-- and README.md's "Open questions" section for the explicit ask to Jed.
--
-- Design notes:
-- - collision.site: no real site names are known to this bot (no source
--   document confirms the actual site name(s) beyond "South" used only as
--   placeholder test data in scripts/verify_002.sql — never treated as
--   real). No placeholder site rows are inserted by this migration. The
--   CSV import / repository layer creates site rows on demand from
--   whatever name a human enters, so this migration does not need to
--   guess Complete Collision's real site list. ADR-001 §4 refers to a
--   "Site entity" as a planned concept; this is that entity.
-- - collision.job.site (TEXT) is dropped in favor of site_id (FK). Since
--   production has 0 job rows (confirmed 2026-09-04 immediately before
--   writing this migration), there is no real data to backfill or lose.
-- - collision.cost_entry is additive only (new table, no existing column
--   changes) and NOT a replacement for collision.job's four cost columns
--   — pdr_settlement.py's RepairOrder dataclass still reads those columns
--   directly. cost_entry is an itemized ledger (multiple line items per
--   RO: parts, labor, paint/materials, sublet, rental reimbursement,
--   other) that the application layer can use to build up / reconcile
--   those aggregate columns. No trigger auto-syncs cost_entry totals into
--   collision.job's columns in this migration — kept as an explicit
--   application-layer reconciliation step for Phase 1 (see
--   app/repository.py's recalculate_job_costs_from_entries()), to avoid
--   silently overwriting a manually-entered aggregate with a possibly
--   incomplete itemized total. OPEN QUESTION for Jed: should job's totals
--   become fully derived from cost_entry once itemized entry is the norm,
--   or should both coexist indefinitely (e.g. cost_entry for detail,
--   job's columns as the human-confirmed number of record)?
-- - cost_entry.category enum values are this bot's own reasonable body-
--   shop cost taxonomy (parts, labor, paint_materials, sublet,
--   rental_reimbursement, other) — NOT sourced from a Complete Collision
--   document. Flagged as an assumption Jed should correct if his actual
--   categories differ; changing an enum's value set later is a normal,
--   low-risk migration (ALTER TYPE ... ADD VALUE) as long as no row has
--   used a value being removed.

-- ---------------------------------------------------------------------------
-- collision.site — real entity. Created on demand by the app/CSV import
-- layer (find-or-create by name), not pre-populated with guessed names.
-- ---------------------------------------------------------------------------

CREATE TABLE collision.site (
  id                BIGSERIAL PRIMARY KEY,
  name              TEXT NOT NULL,
  address           TEXT,
  active            BOOLEAN NOT NULL DEFAULT true,

  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        TEXT NOT NULL,

  CONSTRAINT site_name_unique UNIQUE (name)
);

-- ---------------------------------------------------------------------------
-- collision.job.site_id replaces collision.job.site (TEXT). Production has
-- 0 job rows as of this migration (confirmed by direct query) so this is a
-- clean cutover, not a backfill of real data. See header note: held on
-- staging pending Jed's sign-off to promote given it drops a live
-- production column.
-- ---------------------------------------------------------------------------

ALTER TABLE collision.job ADD COLUMN site_id BIGINT REFERENCES collision.site (id);
ALTER TABLE collision.job DROP COLUMN site;
ALTER TABLE collision.job ALTER COLUMN site_id SET NOT NULL;

CREATE INDEX idx_job_site_id ON collision.job (site_id);

-- ---------------------------------------------------------------------------
-- collision.cost_entry — itemized cost ledger per job. Additive only.
-- ---------------------------------------------------------------------------

CREATE TYPE collision.cost_category AS ENUM (
  'parts',
  'labor',
  'paint_materials',
  'sublet',
  'rental_reimbursement',
  'other'
);

CREATE TABLE collision.cost_entry (
  id                BIGSERIAL PRIMARY KEY,
  job_id            BIGINT NOT NULL REFERENCES collision.job (id),

  category          collision.cost_category NOT NULL,
  description       TEXT,
  amount            NUMERIC(12,2) NOT NULL,
  incurred_at       DATE NOT NULL DEFAULT CURRENT_DATE,

  -- Provenance: was this entered by hand in the dashboard, or imported
  -- from a manual CSV export a human pulled out of CCC ONE? Never
  -- 'ccc_one_api' or similar — no automated CCC ONE read exists or is
  -- planned for v1 (ADR-001 §1).
  source            TEXT NOT NULL DEFAULT 'manual',
  source_file       TEXT,  -- CSV filename, when source = 'csv_import'

  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        TEXT NOT NULL,

  CONSTRAINT cost_entry_amount_nonnegative CHECK (amount >= 0),
  CONSTRAINT cost_entry_source_known CHECK (source IN ('manual', 'csv_import'))
);

CREATE INDEX idx_cost_entry_job ON collision.cost_entry (job_id);
CREATE INDEX idx_cost_entry_category ON collision.cost_entry (job_id, category);

-- ---------------------------------------------------------------------------
-- Grants
-- ---------------------------------------------------------------------------

GRANT SELECT, INSERT, UPDATE ON collision.site TO collision_app;
GRANT SELECT, INSERT ON collision.cost_entry TO collision_app;  -- append-only,
  -- same rationale as collision.estimate/job_event: a correction to a cost
  -- entry is a new row (e.g. a negative adjustment entry), not a mutation
  -- of what was originally recorded, preserving an honest audit trail for
  -- a financial ledger.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA collision TO collision_app;

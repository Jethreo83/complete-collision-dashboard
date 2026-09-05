-- 011_collision_payment.sql
--
-- collision.payment — the "payment" entity flagged as not-yet-built in
-- docs/SHARED_CONVENTIONS_NOTE.md convention #5 ("Payments — one table
-- shape, accounting_sync_ref reserved for later. Not yet built for
-- Complete Collision -- handoff §2.3 lists `payment` as shared shape
-- with Elektrica -- apply this convention when that table is
-- designed.") and COMPLETE_COLLISION_HANDOFF_2026-09-03.md §2.3
-- ("payment -- shared shape (Elektrica §1.6); migrate
-- cc_payment_audit.json and cc_payment_tracking.json with provenance").
--
-- Also implements CC-6 (ADR-001 §3, Confirmed): "payments recorded/made
-- via API show live in the dashboard; QuickBooks sync is a later,
-- additive step -- not built now," via the same nullable
-- accounting_sync_ref reserved column Elektrica uses.
--
-- SHAPE SOURCE: migrations/011 in this file mirrors
-- elektrica-dashboard-ref/migrations/008_elektrica_payment_toll_compliance.sql's
-- elektrica.payment table field-for-field (source enum, external
-- transaction id, amount, received_at, accounting_sync_ref, append-only
-- via REVOKE + forbid-mutation trigger) -- this is what "shared shape"
-- means per convention #5, not a fresh design. Two structural
-- differences from the Elektrica original, both forced by real schema
-- differences rather than invented:
--   1. rental_id -> job_id (collision.job is this project's RO/rental-
--      equivalent spine; collision.job.id is the correct FK target).
--   2. No demand_id-equivalent column: Elektrica's payment can settle a
--      specific `elektrica.demand` (an insurer dispute demand) as well
--      as a plain rental charge. Complete Collision's ADR-001/handoff
--      have no analogous "demand" entity -- adjuster disputes are
--      tracked via collision.job.posture (paying | fighting) on the RO
--      itself, not a separate row a payment could reference. Omitted
--      rather than invented.
--
-- ASSUMPTION FLAGGED FOR JED: the `source` enum values below
-- (authorize_net | check | insurer_eft | manual) are copied verbatim
-- from Elektrica's payment_source enum because handoff §2.3 says
-- "shared shape (Elektrica §1.6)" -- it does NOT independently confirm
-- Complete Collision actually processes card payments through
-- Authorize.net specifically (unlike Elektrica, where that's the
-- handoff's literal spec). If Complete Collision uses a different card
-- processor or none at all, this enum's value set should be corrected
-- before real payment data is migrated into it -- changing an enum's
-- values later is a normal low-risk migration (ALTER TYPE ... ADD/
-- RENAME VALUE) as long as no row uses a value being removed. Same
-- "flag Jed's actual categories may differ" treatment as migration
-- 006's cost_category enum.
--
-- No CCC ONE dependency: payment amounts/sources are Complete
-- Collision's own money-received record, not anything read from or
-- written to CCC ONE (ADR-001 §1). Real migration of
-- cc_payment_audit.json / cc_payment_tracking.json content into this
-- table remains blocked on export access to "the mini" (unchanged
-- blocker, tracked since 2026-09-03) -- this migration only creates the
-- destination table/shape, no data import.
--
-- Purely additive: new table + new enum type, no existing column
-- touched. Same promotion posture as migrations 001-005/007/008/009
-- (additive, design already specified by an existing convention/
-- decision, no open question requiring Jed's input) -- NOT held to
-- migration 006/010's staging-only bar, which was specifically about a
-- destructive column drop / an unresolved design question, neither of
-- which applies here.

CREATE TYPE collision.payment_source AS ENUM ('authorize_net', 'check', 'insurer_eft', 'manual');

CREATE TABLE collision.payment (
  id                    BIGSERIAL PRIMARY KEY,

  job_id                BIGINT NOT NULL REFERENCES collision.job (id),

  source                collision.payment_source NOT NULL,
  external_transaction_id TEXT,  -- processor txn id, check number, insurer EFT ref

  amount                NUMERIC(12,2) NOT NULL CHECK (amount > 0),
  received_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- Reserved per CC-6 / convention #5, nullable, additive: QuickBooks
  -- sync is a later step, not built now.
  accounting_sync_ref   TEXT,

  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by            TEXT NOT NULL,

  CONSTRAINT payment_external_txn_id_required_for_authorize_net
    CHECK (source <> 'authorize_net' OR external_transaction_id IS NOT NULL)
);

CREATE INDEX idx_payment_job ON collision.payment (job_id);

GRANT SELECT, INSERT ON collision.payment TO collision_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA collision TO collision_app;

-- Payments are a financial record -- append-only, same philosophy as
-- collision.job_event / collision.cost_entry / collision.estimate
-- (migrations 002/003/006) and elektrica.payment. A correction is a
-- new row (e.g. a reversal), never an edit to history.
REVOKE DELETE, UPDATE ON collision.payment FROM PUBLIC;

CREATE OR REPLACE FUNCTION collision.payment_forbid_mutation()
RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'collision.payment is an append-only financial record: % is not permitted (id=%)', TG_OP, OLD.id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_payment_forbid_delete
  BEFORE DELETE ON collision.payment
  FOR EACH ROW EXECUTE FUNCTION collision.payment_forbid_mutation();

CREATE TRIGGER trg_payment_forbid_update
  BEFORE UPDATE ON collision.payment
  FOR EACH ROW EXECUTE FUNCTION collision.payment_forbid_mutation();

-- ---------------------------------------------------------------------------
-- Lightweight per-job payment total view -- same "aging/blocked view as a
-- query, not a stored column" philosophy as
-- elektrica.vehicle_revenue_summary / elektrica.compliance_items_expiring_soon,
-- and as collision.job_labor_cost_total()/job_direct_cost_total()
-- (migration 010). Useful once app/repository.py needs "total collected
-- on this RO" without duplicating the sum in application code.
-- ---------------------------------------------------------------------------

CREATE VIEW collision.job_payment_summary AS
SELECT
  j.id AS job_id,
  j.ro_number,
  COALESCE(SUM(p.amount), 0) AS total_collected,
  count(p.id) AS payment_count,
  max(p.received_at) AS last_payment_at
FROM collision.job j
LEFT JOIN collision.payment p ON p.job_id = j.id
GROUP BY j.id, j.ro_number;

GRANT SELECT ON collision.job_payment_summary TO collision_app;

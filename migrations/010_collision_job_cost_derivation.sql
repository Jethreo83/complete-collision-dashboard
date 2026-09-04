-- 010_collision_job_cost_derivation.sql
--
-- Jed's answer (relayed via hermes, 2026-09-06) to migration 006's open
-- question: "job.cost totals should become FULLY DERIVED from the
-- itemized collision.cost_entry ledger once itemized entry is standard
-- - not coexist indefinitely." Jed's follow-up (2026-09-06, second
-- relay) confirmed scope: gross_revenue and rent_utility_share stay
-- human-entered (one's revenue not a cost, the other is explicitly
-- non-itemized overhead per migration 006's own design); labor_cost and
-- direct_ro_costs become derived. This migration implements that.
--
-- *** CORRECTION FROM FIRST DRAFT OF THIS FILE: this session's first
-- attempt used GENERATED ALWAYS ... STORED columns calling a STABLE SQL
-- function that queried collision.cost_entry. That failed at apply time
-- with "generation expression is not immutable" -- and marking the
-- function IMMUTABLE would be a lie (its result changes whenever
-- cost_entry changes) and Postgres would likely still reject it, or
-- worse, silently cache a stale value if it somehow didn't. The real
-- issue isn't volatility -- Postgres GENERATED columns are fundamentally
-- restricted to expressions over OTHER COLUMNS OF THE SAME ROW; they
-- cannot query another table AT ALL, full stop. This was a genuine
-- design error in the first draft, caught by actually running it against
-- staging rather than assuming the SQL would work, not by review. ***
--
-- TRANSITION MECHANISM (corrected): AFTER trigger on collision.cost_entry
-- that recalculates and writes collision.job.labor_cost/direct_ro_costs,
-- PLUS a column-level REVOKE that removes collision_app's ability to
-- write those two specific columns directly on collision.job. Together
-- these give the actual guarantee Jed asked for ("not separately
-- human-entered"):
--   - The app genuinely CANNOT set labor_cost/direct_ro_costs via any
--     INSERT/UPDATE on collision.job while connected as collision_app
--     -- Postgres enforces this at the grant level, not by convention or
--     code discipline.
--   - The only way those columns change is the trigger firing off a real
--     cost_entry row being inserted/updated/deleted -- so the value is
--     always genuinely "derived from the ledger," matching Jed's intent,
--     without the earlier design's Postgres-incompatible mechanics.
--   - The trigger function runs as SECURITY DEFINER (owned by this
--     migration's applying role, i.e. neondb_owner) specifically so it
--     can write those two columns despite collision_app's REVOKE --
--     this is the standard Postgres pattern for "only a specific,
--     reviewed code path may write X," stronger than an app-layer
--     convention.
--   - collision.job's UPDATE grant otherwise stays intact for
--     collision_app (status transitions, gross_revenue, etc. are
--     unaffected) -- only labor_cost/direct_ro_costs are locked down.
--
-- Previously considered and still rejected for the reasons in the first
-- draft's comments (preserved for the record, still valid):
--   - A separate view: bigger blast radius, risk of two different
--     numbers being read depending on which relation a query hits.
--   - An app-layer "opt-in reconciliation" call (migration 006's
--     original design, superseded here): doesn't satisfy "not
--     separately human-entered" -- a human/app can still just not call
--     it, or call it against an incomplete set of cost_entry rows and
--     leave a stale value in place indefinitely.
--
-- SAFETY: production has 0 job rows and 0 cost_entry rows (confirmed
-- 2026-09-06 immediately before writing this migration). The trigger
-- recalculates on every cost_entry write, so there's nothing to backfill
-- for existing rows -- if that assumption stops holding before this
-- promotes, existing job rows' labor_cost/direct_ro_costs need a one-time
-- UPDATE ... SET labor_cost = collision.job_labor_cost_total(id), ...
-- backfill pass (using the read-only helper functions below) before the
-- REVOKE takes effect, or every existing job would show 0 until its next
-- cost_entry write. Flagged for whoever promotes this if that changes.

-- ---------------------------------------------------------------------------
-- Read-only helper functions -- kept from the first draft, still useful
-- (e.g. for the one-time backfill above, or ad-hoc reporting), just no
-- longer used inside a GENERATED column expression.
-- ---------------------------------------------------------------------------

CREATE FUNCTION collision.job_labor_cost_total(p_job_id BIGINT)
RETURNS NUMERIC(12,2)
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(SUM(amount), 0.00)
  FROM collision.cost_entry
  WHERE job_id = p_job_id AND category = 'labor';
$$;

CREATE FUNCTION collision.job_direct_cost_total(p_job_id BIGINT)
RETURNS NUMERIC(12,2)
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(SUM(amount), 0.00)
  FROM collision.cost_entry
  WHERE job_id = p_job_id AND category <> 'labor';
$$;

-- ---------------------------------------------------------------------------
-- Trigger function: recalculates one job's labor_cost/direct_ro_costs
-- from cost_entry, fired after any INSERT/UPDATE/DELETE on cost_entry.
-- SECURITY DEFINER so it can write collision.job's locked-down columns
-- even though collision_app (the role that will actually fire this
-- trigger by inserting cost_entry rows) has no UPDATE grant on those
-- columns itself.
-- ---------------------------------------------------------------------------

CREATE FUNCTION collision.recalculate_job_costs_trigger()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = collision, pg_temp
AS $$
DECLARE
  v_job_id BIGINT;
BEGIN
  v_job_id := COALESCE(NEW.job_id, OLD.job_id);
  UPDATE collision.job
  SET labor_cost = collision.job_labor_cost_total(v_job_id),
      direct_ro_costs = collision.job_direct_cost_total(v_job_id),
      updated_at = now(),
      updated_by = 'collision.recalculate_job_costs_trigger'
  WHERE id = v_job_id;
  RETURN NULL;  -- AFTER trigger, return value ignored
END;
$$;

CREATE TRIGGER cost_entry_recalculate_job_costs
AFTER INSERT OR UPDATE OR DELETE ON collision.cost_entry
FOR EACH ROW
EXECUTE FUNCTION collision.recalculate_job_costs_trigger();

-- ---------------------------------------------------------------------------
-- Lock down direct writes to labor_cost/direct_ro_costs from collision_app.
--
-- *** CORRECTION, caught by actually running the verify script rather
-- than assuming: a plain REVOKE UPDATE (labor_cost, direct_ro_costs) ...
-- does NOT work here, and Postgres's own privilege model explains why --
-- collision_app already has a TABLE-LEVEL UPDATE grant on collision.job
-- (from migration 002/006), stored in the table's relacl. A column-level
-- REVOKE only removes a column-level grant recorded in that column's own
-- attacl; it cannot override a table-level grant that already covers
-- every column. The two are independent ACL entries, and Postgres
-- allows either one to satisfy an UPDATE check (effectively OR'd) --
-- confirmed via information_schema.column_privileges still showing
-- collision_app with UPDATE on labor_cost/direct_ro_costs even after
-- the column-level REVOKE ran, and verify_010.sql's CHECK 4 failing for
-- real (not a test bug) as a result.
--
-- REAL FIX: revoke the table-wide UPDATE grant entirely, then re-grant
-- UPDATE at the COLUMN level for every column EXCEPT labor_cost/
-- direct_ro_costs. This is the only way Postgres actually supports
-- "UPDATE this table's columns except these two." ***
-- ---------------------------------------------------------------------------

REVOKE UPDATE ON collision.job FROM collision_app;

GRANT UPDATE (
  ro_number, vehicle_id, customer_id, site_id, category, status,
  claim_number, insurer, adjuster_name, posture,
  gross_revenue, rent_utility_share,
  ccc_one_last_reconciled_at, opened_at, closed_at, collected_at,
  updated_at, updated_by
) ON collision.job TO collision_app;

-- Same issue applies to INSERT -- collision_app has table-level INSERT
-- from migration 002, which a column-level REVOKE cannot override
-- either. Same fix: revoke table-wide INSERT, re-grant at column level
-- for every column except labor_cost/direct_ro_costs (both of which
-- have DEFAULT 0 and will populate correctly without collision_app ever
-- supplying a value).
REVOKE INSERT ON collision.job FROM collision_app;

GRANT INSERT (
  ro_number, vehicle_id, customer_id, site_id, category, status,
  claim_number, insurer, adjuster_name, posture,
  gross_revenue, rent_utility_share,
  ccc_one_last_reconciled_at, opened_at, closed_at, collected_at,
  created_by, updated_by
) ON collision.job TO collision_app;

-- ---------------------------------------------------------------------------
-- app/repository.py follow-up required, NOT done in this SQL migration:
-- create_repair_order()'s INSERT statement currently names labor_cost
-- and direct_ro_costs explicitly (with ro.labor_cost/ro.direct_ro_costs
-- values) -- after the REVOKE above, that INSERT will fail under
-- collision_app with insufficient_privilege the moment this migration
-- is live. repository.py needs a matching code change (drop those two
-- columns from create_repair_order()'s INSERT list entirely, always
-- start a new job at 0/0 via the column DEFAULT until cost_entry rows
-- exist) BEFORE or WITH this migration's promotion -- not safe to
-- promote to production alongside unmodified app code. Same for
-- recalculate_costs_from_entries() (migration 006's original app-layer
-- reconciliation step): it becomes genuinely dead code once the trigger
-- exists (its UPDATE will also now fail under collision_app for the
-- same reason) -- should be removed, not left in as a landmine.
-- ---------------------------------------------------------------------------

GRANT EXECUTE ON FUNCTION collision.job_labor_cost_total(BIGINT) TO collision_app;
GRANT EXECUTE ON FUNCTION collision.job_direct_cost_total(BIGINT) TO collision_app;

-- labor_cost/direct_ro_costs need a DEFAULT of 0 now that collision_app
-- can no longer supply an initial value at INSERT time (existing column
-- definitions from migrations 002/006 have no DEFAULT).
ALTER TABLE collision.job ALTER COLUMN labor_cost SET DEFAULT 0;
ALTER TABLE collision.job ALTER COLUMN direct_ro_costs SET DEFAULT 0;

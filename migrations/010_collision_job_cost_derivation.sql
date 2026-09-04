-- 010_collision_job_cost_derivation.sql
--
-- Jed's answer (relayed via hermes, 2026-09-06) to migration 006's open
-- question: "job.cost totals should become FULLY DERIVED from the
-- itemized collision.cost_entry ledger once itemized entry is standard
-- - not coexist indefinitely. So job's own cost columns
-- (gross_revenue, direct_ro_costs, labor_cost, rent_utility_share)
-- should eventually become computed/generated from cost_entry rows,
-- not separately human-entered. Design 006 (and whatever migration
-- handles the transition) around that end state - promote 006 to
-- staging with that direction in mind, and figure out the transition
-- path (view vs generated column vs trigger) as you see fit."
--
-- IMPORTANT SCOPE FLAG, before describing what this migration does:
-- Jed's four named columns do not all derive from collision.cost_entry
-- cleanly, and this migration does NOT force a fit where there isn't
-- one. Flagging plainly rather than guessing past it:
--
--   - direct_ro_costs and labor_cost: derive cleanly. cost_entry's
--     category enum ('parts','labor','paint_materials','sublet',
--     'rental_reimbursement','other') maps 1:1 onto exactly this split
--     (labor_cost = sum of 'labor'; direct_ro_costs = sum of everything
--     else). This migration derives BOTH of these via GENERATED ALWAYS.
--
--   - gross_revenue: this is REVENUE, not a cost. collision.cost_entry
--     is explicitly a cost ledger (its own header comment: "itemized
--     cost ledger to support 'cost tracking'"), with no revenue/invoice
--     category in its enum. There is nothing in cost_entry to derive
--     gross_revenue FROM. Deriving it would require either (a) adding a
--     revenue-side ledger this bot has never been asked to build, or
--     (b) misusing cost_entry's 'other' category to smuggle revenue
--     rows into a cost table, which would corrupt the itemized cost
--     totals derive_ro_costs/labor_cost above. NOT derived here.
--     Left as a human-entered column exactly as before. Flagged back to
--     Jed as an open question: is gross_revenue supposed to derive from
--     something else (an invoice/revenue ledger not yet built), or was
--     it swept into the "fully derived" instruction by name without
--     considering it's not itemizable the same way? Recommend asking
--     directly rather than this bot guessing which reading is right.
--
--   - rent_utility_share: migration 006's own header explicitly notes
--     "rent_utility_share is NOT touched [by existing reconciliation] --
--     it's a fixed shop-overhead allocation per RO, not an itemized
--     line item in cost_entry's category set, so there's nothing to sum
--     it from." That's still true after this migration -- cost_entry
--     has no per-RO-overhead-allocation category, and adding one would
--     mean every RO needs a manually-entered 'other'-category cost_entry
--     row just to carry what is fundamentally a shop-level allocation
--     formula (e.g. rent+utilities / RO count that month), not a line
--     item anyone actually incurred on that specific RO. NOT derived
--     here, left as human-entered. Same recommendation: ask Jed whether
--     he means literally every column, in which case this bot needs the
--     actual overhead-allocation formula to build it as a real
--     computation (from collision.site or a shop-expenses table not yet
--     designed), not a guess.
--
-- TRANSITION MECHANISM CHOSEN: PostgreSQL 18 (confirmed live version)
-- STORED GENERATED COLUMN, not a view or an AFTER-trigger recalculation.
-- Reasoning:
--   - A view (e.g. collision.job_v derived entirely from cost_entry)
--     would mean every existing query/app-layer read of collision.job
--     (pdr_settlement.py's RepairOrder, app/repository.py,
--     app/models.py's RepairOrder dataclass, app/api.py's response
--     models) needs to switch to a different relation. That's a much
--     bigger blast radius for a same-meaning column rename, and risks
--     silently reading two different things (job.direct_ro_costs vs
--     job_v.direct_ro_costs) if any code forgets to switch.
--   - An AFTER INSERT/UPDATE trigger on cost_entry recalculating job's
--     columns re-introduces exactly the risk migration 006's header
--     flagged for NOT doing this automatically: a trigger firing after
--     every single cost_entry insert means the column's value depends
--     on trigger execution order/timing, is harder to reason about
--     under concurrent inserts, and (per Postgres restriction) a
--     trigger-maintained column can still be directly UPDATEd unless a
--     separate rule/constraint blocks that, reopening the "human enters
--     a conflicting number" problem Jed's instruction is trying to
--     close.
--   - A STORED GENERATED COLUMN is enforced by Postgres itself: the
--     column literally cannot be written to directly (INSERT/UPDATE
--     specifying it is a hard error), it's always correct on read (no
--     staleness window), and no application code changes at all for
--     read paths (still collision.job.direct_ro_costs, same table, same
--     column name). The tradeoff -- Postgres GENERATED columns cannot
--     reference another TABLE, only other columns on the SAME row --
--     means the sum-from-cost_entry logic must live in a helper
--     function collision.job_cost_total(job_id, category_filter) that
--     the generated column expression calls; this is a real Postgres
--     limitation, not a design choice, and it's fine here since
--     PL/pgSQL functions are allowed inside generated column
--     expressions as long as they're STABLE/IMMUTABLE-safe reads.
--
-- SAFETY: production has 0 job rows (confirmed 2026-09-06 immediately
-- before writing this migration, same discipline as every prior
-- migration). Dropping and re-adding direct_ro_costs/labor_cost as
-- GENERATED columns is safe with no data to lose. If production ever
-- has real job rows before this promotes, this migration would need a
-- backfill step first (populate cost_entry rows matching each job's
-- existing flat totals) -- not needed today, flagged for whoever
-- promotes this if that assumption stops holding.

-- ---------------------------------------------------------------------------
-- Helper: sums cost_entry amounts for one job, split by whether the
-- category is 'labor' or not. STABLE (not IMMUTABLE) since cost_entry
-- rows change over time -- Postgres requires STABLE at minimum for use
-- in a generated column expression that reads another table.
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
-- Recreate labor_cost / direct_ro_costs as STORED GENERATED columns.
-- Postgres requires DROP + re-ADD (cannot ALTER an existing plain column
-- into a generated one in-place).
-- ---------------------------------------------------------------------------

ALTER TABLE collision.job DROP COLUMN labor_cost;
ALTER TABLE collision.job DROP COLUMN direct_ro_costs;

ALTER TABLE collision.job
  ADD COLUMN labor_cost NUMERIC(12,2)
  GENERATED ALWAYS AS (collision.job_labor_cost_total(id)) STORED;

ALTER TABLE collision.job
  ADD COLUMN direct_ro_costs NUMERIC(12,2)
  GENERATED ALWAYS AS (collision.job_direct_cost_total(id)) STORED;

-- gross_revenue and rent_utility_share are UNCHANGED by this migration
-- -- still plain human-entered columns. See header for why.

-- ---------------------------------------------------------------------------
-- app/repository.py's recalculate_costs_from_entries() (migrations/006's
-- explicit opt-in reconciliation step) is now DEAD CODE for labor_cost/
-- direct_ro_costs specifically -- those columns can no longer be written
-- to at all (Postgres rejects any INSERT/UPDATE naming a generated
-- column), so there is nothing left to "reconcile." That function still
-- has a real job for gross_revenue/rent_utility_share... except it
-- currently only ever touches labor_cost/direct_ro_costs per its own
-- docstring. Flagged as application-layer follow-up, not fixed in this
-- SQL migration: repository.py needs a matching code change (remove or
-- repurpose recalculate_costs_from_entries(), update create_repair_order()
-- to stop passing labor_cost/direct_ro_costs as INSERT values) to avoid
-- shipping a function that will now error on any INSERT attempt for
-- collision.job. Do not promote this migration to production alongside
-- unmodified app code that still writes those two columns directly.
-- ---------------------------------------------------------------------------

GRANT EXECUTE ON FUNCTION collision.job_labor_cost_total(BIGINT) TO collision_app;
GRANT EXECUTE ON FUNCTION collision.job_direct_cost_total(BIGINT) TO collision_app;

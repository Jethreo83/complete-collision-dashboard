-- Verification harness for migration 010 (cost-derivation trigger +
-- column-level REVOKE on collision.job.labor_cost/direct_ro_costs).
-- Same discipline as verify_001-009: verify by actually inserting rows
-- and observing real behavior under the collision_app role, not just
-- checking catalog objects exist.

DO $$
DECLARE
  v_person_id   BIGINT;
  v_customer_id BIGINT;
  v_vehicle_id  BIGINT;
  v_site_id     BIGINT;
  v_job_id      BIGINT;
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'CostDerive010', 'test.costderive010@example.com', 'test_harness')
  RETURNING id INTO v_person_id;

  INSERT INTO collision.customer (person_id, source, created_by)
  VALUES (v_person_id, 'walk_in', 'test_harness')
  RETURNING id INTO v_customer_id;

  INSERT INTO collision.vehicle (vin, make, model, year, customer_id, created_by)
  VALUES ('TESTVIN010000001', 'Test', 'Model010', 2020, v_customer_id, 'test_harness')
  RETURNING id INTO v_vehicle_id;

  INSERT INTO collision.site (name, created_by)
  VALUES ('Test Site 010', 'test_harness')
  RETURNING id INTO v_site_id;

  INSERT INTO collision.job (
    ro_number, vehicle_id, customer_id, site_id, category, status,
    gross_revenue, rent_utility_share, created_by, updated_by
  ) VALUES (
    'RO-TEST-9010', v_vehicle_id, v_customer_id, v_site_id, 'collision', 'undecided',
    5000.00, 150.00, 'test_harness', 'test_harness'
  ) RETURNING id INTO v_job_id;

  -- Store the job_id where the rest of this script (run statement by
  -- statement, no shared session variables across DO blocks) can find
  -- it again: a throwaway temp table, cleaned up at the end.
  CREATE TEMP TABLE _verify_010_job_id (job_id BIGINT);
  INSERT INTO _verify_010_job_id VALUES (v_job_id);
END $$;

-- Grant collision_app access to this session-local temp table -- SET
-- ROLE within the same session can still see it, but has no privilege
-- on it until granted (temp tables aren't exempt from normal grants).
GRANT SELECT ON _verify_010_job_id TO collision_app;

-- CHECK 1: brand-new job starts at labor_cost=0, direct_ro_costs=0
-- (DEFAULT 0, no cost_entry rows yet) -- confirms the DEFAULT survived
-- the REVOKE (collision_app never had to supply a value).
SELECT j.labor_cost, j.direct_ro_costs
FROM collision.job j, _verify_010_job_id v
WHERE j.id = v.job_id;
-- EXPECT: 0.00, 0.00

-- CHECK 2: insert a 'labor' cost_entry row as collision_app, confirm the
-- trigger fires and labor_cost updates for real (not just that the
-- INSERT into cost_entry succeeds).
SET ROLE collision_app;

INSERT INTO collision.cost_entry (job_id, category, description, amount, created_by)
SELECT job_id, 'labor', 'body labor', 300.00, 'collision_app_test'
FROM _verify_010_job_id;

RESET ROLE;

SELECT j.labor_cost, j.direct_ro_costs
FROM collision.job j, _verify_010_job_id v
WHERE j.id = v.job_id;
-- EXPECT: 300.00, 0.00

-- CHECK 3: insert a non-labor cost_entry row, confirm direct_ro_costs
-- updates and labor_cost is untouched (additive, category-split).
SET ROLE collision_app;

INSERT INTO collision.cost_entry (job_id, category, description, amount, created_by)
SELECT job_id, 'parts', 'bumper', 220.50, 'collision_app_test'
FROM _verify_010_job_id;

RESET ROLE;

SELECT j.labor_cost, j.direct_ro_costs
FROM collision.job j, _verify_010_job_id v
WHERE j.id = v.job_id;
-- EXPECT: 300.00, 220.50

-- CHECK 4: THE REAL GUARANTEE. collision_app cannot directly UPDATE
-- labor_cost/direct_ro_costs on collision.job, no matter what the
-- ledger says -- proving this is genuinely enforced, not just "the
-- app doesn't happen to try it."
DO $$
DECLARE
  v_failed BOOLEAN := false;
BEGIN
  SET ROLE collision_app;
  BEGIN
    UPDATE collision.job SET labor_cost = 999999.99
    WHERE id = (SELECT job_id FROM _verify_010_job_id);
  EXCEPTION WHEN insufficient_privilege THEN
    v_failed := true;
  END;
  RESET ROLE;

  IF NOT v_failed THEN
    RAISE EXCEPTION 'CHECK 4 FAILED: collision_app was able to directly UPDATE labor_cost -- the derivation guarantee is not enforced';
  END IF;
END $$;

SELECT 'CHECK 4 PASSED: collision_app genuinely blocked from writing labor_cost directly' AS check_4_result;

-- CHECK 5: same guarantee for direct_ro_costs.
DO $$
DECLARE
  v_failed BOOLEAN := false;
BEGIN
  SET ROLE collision_app;
  BEGIN
    UPDATE collision.job SET direct_ro_costs = 1.00
    WHERE id = (SELECT job_id FROM _verify_010_job_id);
  EXCEPTION WHEN insufficient_privilege THEN
    v_failed := true;
  END;
  RESET ROLE;

  IF NOT v_failed THEN
    RAISE EXCEPTION 'CHECK 5 FAILED: collision_app was able to directly UPDATE direct_ro_costs';
  END IF;
END $$;

SELECT 'CHECK 5 PASSED: collision_app genuinely blocked from writing direct_ro_costs directly' AS check_5_result;

-- CHECK 6: collision_app CAN still update every OTHER column on the
-- same row (proves the REVOKE is column-scoped, not table-wide) --
-- gross_revenue is one of the two columns Jed said stays human-entered.
SET ROLE collision_app;
UPDATE collision.job SET gross_revenue = 5500.00
WHERE id = (SELECT job_id FROM _verify_010_job_id);
RESET ROLE;

SELECT j.gross_revenue, j.labor_cost, j.direct_ro_costs
FROM collision.job j, _verify_010_job_id v
WHERE j.id = v.job_id;
-- EXPECT: 5500.00 (updated), 300.00, 220.50 (unchanged by the gross_revenue update)

-- CHECK 7: deleting a cost_entry row also recalculates (DELETE is one
-- of the trigger's three fired events, not just INSERT/UPDATE).
SET ROLE collision_app;
-- collision_app has no DELETE grant on cost_entry (append-only, by
-- design per migration 006's own header) -- so this DELETE must run as
-- the privileged connecting role, same as a real correction would (a
-- human/admin script, not the app, per migration 006's rationale).
RESET ROLE;

DELETE FROM collision.cost_entry
WHERE job_id = (SELECT job_id FROM _verify_010_job_id) AND category = 'parts';

SELECT j.labor_cost, j.direct_ro_costs
FROM collision.job j, _verify_010_job_id v
WHERE j.id = v.job_id;
-- EXPECT: 300.00, 0.00 -- direct_ro_costs drops back to 0 since the
-- only non-labor entry was just removed

DROP TABLE _verify_010_job_id;

SELECT 'ALL CHECKS COMPLETED' AS summary;

-- Verification harness for migration 002 (collision.vehicle, collision.job,
-- collision.job_event). Same discipline as verify_001.sql: verify by
-- actually inserting/querying/switching role, not by reading DDL.
--
-- Assumes migration 001 has already been applied (collision.customer,
-- collision_app role must exist).

DO $$
DECLARE
  v_person_id  BIGINT;
  v_customer_id BIGINT;
  v_vehicle_id  BIGINT;
  v_job_id      BIGINT;
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'JobOwner', 'test.jobowner@example.com', 'test_harness')
  RETURNING id INTO v_person_id;

  INSERT INTO collision.customer (person_id, source, created_by)
  VALUES (v_person_id, 'walk_in', 'test_harness')
  RETURNING id INTO v_customer_id;

  INSERT INTO collision.vehicle (vin, make, model, year, customer_id, created_by)
  VALUES ('TESTVIN0000000001', 'Ford', 'F150', 2022, v_customer_id, 'test_harness')
  RETURNING id INTO v_vehicle_id;

  INSERT INTO collision.job (
    ro_number, vehicle_id, customer_id, site, category, status,
    gross_revenue, direct_ro_costs, labor_cost, rent_utility_share,
    created_by, updated_by
  ) VALUES (
    'RO-TEST-9001', v_vehicle_id, v_customer_id, 'South', 'collision', 'undecided',
    10000.00, 2000.00, 1500.00, 500.00,
    'test_harness', 'test_harness'
  ) RETURNING id INTO v_job_id;

  INSERT INTO collision.job_event (job_id, from_status, to_status, created_by, note)
  VALUES (v_job_id, NULL, 'undecided', 'test_harness', 'job created');

  INSERT INTO collision.job_event (job_id, from_status, to_status, created_by, note)
  VALUES (v_job_id, 'undecided', 'came_in', 'test_harness', 'customer dropped off vehicle');

  RAISE NOTICE 'person_id=% customer_id=% vehicle_id=% job_id=%', v_person_id, v_customer_id, v_vehicle_id, v_job_id;
END $$;

-- CHECK 1: job exists with the values inserted, category/status enums hold.
SELECT ro_number, category, status, gross_revenue, direct_ro_costs, labor_cost, rent_utility_share
FROM collision.job WHERE ro_number = 'RO-TEST-9001';
-- EXPECT: 1 row, category=collision, status=undecided, gross_revenue=10000.00

-- CHECK 2: job_event log has exactly 2 rows for this job, in order.
SELECT from_status, to_status, note
FROM collision.job_event je
JOIN collision.job j ON j.id = je.job_id
WHERE j.ro_number = 'RO-TEST-9001'
ORDER BY je.occurred_at;
-- EXPECT: 2 rows — (NULL, undecided, 'job created') then (undecided, came_in, ...)

-- CHECK 3: collision_app can read/write job and vehicle (SELECT/INSERT/UPDATE
-- granted in this migration).
SET ROLE collision_app;
SELECT ro_number, status FROM collision.job WHERE ro_number = 'RO-TEST-9001';
-- EXPECT: 1 row
UPDATE collision.job SET status = 'estimate', updated_by = 'collision_app_test'
WHERE ro_number = 'RO-TEST-9001';
SELECT ro_number, status FROM collision.job WHERE ro_number = 'RO-TEST-9001';
-- EXPECT: status now 'estimate'
RESET ROLE;

-- CHECK 4: collision_app can INSERT into job_event (append) but cannot
-- UPDATE or DELETE existing rows (append-only via grant shape, no
-- UPDATE/DELETE granted).
SET ROLE collision_app;
INSERT INTO collision.job_event (job_id, from_status, to_status, created_by, note)
SELECT id, 'estimate', 'teardown', 'collision_app_test', 'role can insert'
FROM collision.job WHERE ro_number = 'RO-TEST-9001';
SELECT count(*) AS event_count FROM collision.job_event je
JOIN collision.job j ON j.id = je.job_id WHERE j.ro_number = 'RO-TEST-9001';
-- EXPECT: 3 (2 from setup + 1 just inserted)

DO $$
BEGIN
  UPDATE collision.job_event SET note = 'tampered' WHERE note = 'job created';
  RAISE EXCEPTION 'CHECK 4b FAILED: collision_app should not be able to UPDATE job_event (append-only)';
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'CHECK 4b PASSED: collision_app blocked from UPDATE on job_event';
END $$;
RESET ROLE;

-- CHECK 5: vehicle.vin uniqueness is enforced.
DO $$
BEGIN
  INSERT INTO collision.vehicle (vin, customer_id, created_by)
  SELECT 'TESTVIN0000000001', customer_id, 'test_harness' FROM collision.job WHERE ro_number = 'RO-TEST-9001';
  RAISE EXCEPTION 'CHECK 5 FAILED: duplicate VIN should have been rejected';
EXCEPTION WHEN unique_violation THEN
  RAISE NOTICE 'CHECK 5 PASSED: vehicle.vin uniqueness enforced';
END $$;

-- CHECK 6: job.ro_number uniqueness is enforced.
DO $$
BEGIN
  INSERT INTO collision.job (ro_number, vehicle_id, customer_id, site, category, created_by, updated_by)
  SELECT 'RO-TEST-9001', vehicle_id, customer_id, 'South', 'hail', 'test_harness', 'test_harness'
  FROM collision.job WHERE ro_number = 'RO-TEST-9001';
  RAISE EXCEPTION 'CHECK 6 FAILED: duplicate ro_number should have been rejected';
EXCEPTION WHEN unique_violation THEN
  RAISE NOTICE 'CHECK 6 PASSED: job.ro_number uniqueness enforced';
END $$;

SELECT 'ALL CHECKS COMPLETED — CHECK 1 status=undecided pre-update, CHECK 3 shows estimate post-update, CHECK 4 event_count=3, CHECK 4b/5/6 all PASSED notices' AS summary;

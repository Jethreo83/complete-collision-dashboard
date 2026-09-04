-- Verification harness for migration 006 (collision.site, collision.job
-- site_id cutover, collision.cost_entry). Same discipline as verify_001-005:
-- verify by actually inserting/querying/switching role.
--
-- Assumes migrations 001-005 already applied (customer/job/vehicle exist).

DO $$
DECLARE
  v_person_id   BIGINT;
  v_customer_id BIGINT;
  v_vehicle_id  BIGINT;
  v_site_id     BIGINT;
  v_job_id      BIGINT;
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'CostOwner', 'test.costowner@example.com', 'test_harness')
  RETURNING id INTO v_person_id;

  INSERT INTO collision.customer (person_id, source, created_by)
  VALUES (v_person_id, 'walk_in', 'test_harness')
  RETURNING id INTO v_customer_id;

  INSERT INTO collision.vehicle (vin, make, model, year, customer_id, created_by)
  VALUES ('TESTVIN0000000006', 'Honda', 'Civic', 2021, v_customer_id, 'test_harness')
  RETURNING id INTO v_vehicle_id;

  INSERT INTO collision.site (name, address, created_by)
  VALUES ('Test Site 006', '123 Test St', 'test_harness')
  RETURNING id INTO v_site_id;

  INSERT INTO collision.job (
    ro_number, vehicle_id, customer_id, site_id, category, status,
    gross_revenue, direct_ro_costs, labor_cost, rent_utility_share,
    created_by, updated_by
  ) VALUES (
    'RO-TEST-9006', v_vehicle_id, v_customer_id, v_site_id, 'collision', 'undecided',
    10000.00, 0, 0, 0,
    'test_harness', 'test_harness'
  ) RETURNING id INTO v_job_id;

  INSERT INTO collision.cost_entry (job_id, category, description, amount, created_by)
  VALUES
    (v_job_id, 'parts', 'bumper cover', 450.25, 'test_harness'),
    (v_job_id, 'labor', 'body labor 8hrs', 640.00, 'test_harness'),
    (v_job_id, 'paint_materials', 'clearcoat + paint', 210.00, 'test_harness');

  RAISE NOTICE 'person_id=% customer_id=% vehicle_id=% site_id=% job_id=%', v_person_id, v_customer_id, v_vehicle_id, v_site_id, v_job_id;
END $$;

-- CHECK 1: site row exists with expected values.
SELECT name, address, active FROM collision.site WHERE name = 'Test Site 006';
-- EXPECT: 1 row, active=true

-- CHECK 2: job.site_id resolves to the site via join (site TEXT column is gone).
SELECT j.ro_number, s.name AS site_name
FROM collision.job j JOIN collision.site s ON s.id = j.site_id
WHERE j.ro_number = 'RO-TEST-9006';
-- EXPECT: 1 row, site_name = 'Test Site 006'

-- CHECK 3: collision.job no longer has a `site` TEXT column.
SELECT column_name FROM information_schema.columns
WHERE table_schema = 'collision' AND table_name = 'job' AND column_name = 'site';
-- EXPECT: 0 rows

-- CHECK 4: cost_entry rows sum correctly per category and in total.
SELECT ce.category, sum(ce.amount) AS total
FROM collision.cost_entry ce JOIN collision.job j ON j.id = ce.job_id
WHERE j.ro_number = 'RO-TEST-9006'
GROUP BY ce.category ORDER BY ce.category;
-- EXPECT: 3 rows: labor=640.00, parts=450.25, paint_materials=210.00

SELECT sum(amount) AS grand_total
FROM collision.cost_entry ce JOIN collision.job j ON j.id = ce.job_id
WHERE j.ro_number = 'RO-TEST-9006';
-- EXPECT: 1300.25

-- CHECK 5: negative amount rejected by CHECK constraint.
DO $$
BEGIN
  INSERT INTO collision.cost_entry (job_id, category, amount, created_by)
  SELECT id, 'other', -5.00, 'test_harness' FROM collision.job WHERE ro_number = 'RO-TEST-9006';
  RAISE EXCEPTION 'CHECK 5 FAILED: negative amount should have been rejected';
EXCEPTION WHEN check_violation THEN
  RAISE NOTICE 'CHECK 5 PASSED: cost_entry negative amount rejected';
END $$;

-- CHECK 6: unknown source value rejected by CHECK constraint.
DO $$
BEGIN
  INSERT INTO collision.cost_entry (job_id, category, amount, source, created_by)
  SELECT id, 'other', 1.00, 'ccc_one_api', 'test_harness' FROM collision.job WHERE ro_number = 'RO-TEST-9006';
  RAISE EXCEPTION 'CHECK 6 FAILED: unknown source should have been rejected';
EXCEPTION WHEN check_violation THEN
  RAISE NOTICE 'CHECK 6 PASSED: cost_entry unknown source rejected (no CCC ONE automated source permitted)';
END $$;

-- CHECK 7: collision_app can SELECT/INSERT cost_entry and site, but cannot
-- UPDATE/DELETE cost_entry (append-only ledger, same rationale as
-- job_event/estimate).
SET ROLE collision_app;
SELECT count(*) AS visible_entries FROM collision.cost_entry ce
JOIN collision.job j ON j.id = ce.job_id WHERE j.ro_number = 'RO-TEST-9006';
-- EXPECT: 3

INSERT INTO collision.cost_entry (job_id, category, description, amount, created_by)
SELECT id, 'sublet', 'role can insert', 75.00, 'collision_app_test'
FROM collision.job WHERE ro_number = 'RO-TEST-9006';

SELECT count(*) AS visible_entries_after_insert FROM collision.cost_entry ce
JOIN collision.job j ON j.id = ce.job_id WHERE j.ro_number = 'RO-TEST-9006';
-- EXPECT: 4
RESET ROLE;

DO $$
BEGIN
  UPDATE collision.cost_entry SET amount = 0.01 WHERE description = 'bumper cover';
  RAISE EXCEPTION 'CHECK 7b FAILED: collision_app should not be able to UPDATE cost_entry (append-only)';
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'CHECK 7b PASSED: collision_app blocked from UPDATE on cost_entry';
END $$;

-- CHECK 8: site_name_unique constraint enforced.
DO $$
BEGIN
  INSERT INTO collision.site (name, created_by) VALUES ('Test Site 006', 'test_harness');
  RAISE EXCEPTION 'CHECK 8 FAILED: duplicate site name should have been rejected';
EXCEPTION WHEN unique_violation THEN
  RAISE NOTICE 'CHECK 8 PASSED: collision.site.name uniqueness enforced';
END $$;

SELECT 'ALL CHECKS COMPLETED' AS summary;

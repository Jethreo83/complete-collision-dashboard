-- Verification harness for migration 003 (collision.estimate). Same
-- discipline as verify_001/002.sql. Assumes migrations 001 and 002 are
-- already applied (collision.customer, collision.job, collision_app role).

DO $$
DECLARE
  v_person_id   BIGINT;
  v_customer_id BIGINT;
  v_vehicle_id  BIGINT;
  v_job_id      BIGINT;
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'EstimateOwner', 'test.estimateowner@example.com', 'test_harness')
  RETURNING id INTO v_person_id;

  INSERT INTO collision.customer (person_id, source, created_by)
  VALUES (v_person_id, 'walk_in', 'test_harness')
  RETURNING id INTO v_customer_id;

  INSERT INTO collision.vehicle (vin, make, model, year, customer_id, created_by)
  VALUES ('TESTVIN0000000002', 'Toyota', 'Camry', 2023, v_customer_id, 'test_harness')
  RETURNING id INTO v_vehicle_id;

  INSERT INTO collision.job (
    ro_number, vehicle_id, customer_id, site, category, status,
    created_by, updated_by
  ) VALUES (
    'RO-TEST-9002', v_vehicle_id, v_customer_id, 'South', 'collision', 'estimate',
    'test_harness', 'test_harness'
  ) RETURNING id INTO v_job_id;

  RAISE NOTICE 'job_id=%', v_job_id;
END $$;

-- CHECK 1: manual estimate can be inserted fully confirmed at creation.
INSERT INTO collision.estimate (job_id, version, source, draft_content, confirmed_content, confirmed_by, confirmed_at, created_by)
SELECT id, 1, 'manual', '{"lines": [{"op": "bumper", "hours": 3}]}'::jsonb,
       '{"lines": [{"op": "bumper", "hours": 3}]}'::jsonb, 'estimator_jane', now(), 'test_harness'
FROM collision.job WHERE ro_number = 'RO-TEST-9002';

SELECT version, source, confirmed_by FROM collision.estimate e
JOIN collision.job j ON j.id = e.job_id WHERE j.ro_number = 'RO-TEST-9002';
-- EXPECT: 1 row, version=1, source=manual, confirmed_by=estimator_jane

-- CHECK 2: a manual estimate CANNOT be inserted unconfirmed (schema-level
-- Phase 1 scope enforcement, not just a comment).
DO $$
BEGIN
  INSERT INTO collision.estimate (job_id, version, source, draft_content, created_by)
  SELECT id, 2, 'manual', '{"lines": []}'::jsonb, 'test_harness'
  FROM collision.job WHERE ro_number = 'RO-TEST-9002';
  RAISE EXCEPTION 'CHECK 2 FAILED: unconfirmed manual estimate should have been rejected';
EXCEPTION WHEN check_violation THEN
  RAISE NOTICE 'CHECK 2 PASSED: unconfirmed manual estimate rejected by CHECK constraint';
END $$;

-- CHECK 3: a non-manual source (ai_proposed) CAN be inserted unconfirmed
-- (all three confirmation fields NULL together) — the shape exists for
-- Phase 3 even though nothing in this repo writes it yet.
INSERT INTO collision.estimate (job_id, version, source, draft_content, created_by)
SELECT id, 2, 'ai_proposed', '{"lines": [{"op": "fender", "hours": 2}]}'::jsonb, 'test_harness'
FROM collision.job WHERE ro_number = 'RO-TEST-9002';

SELECT version, source, confirmed_content IS NULL AS is_unconfirmed FROM collision.estimate e
JOIN collision.job j ON j.id = e.job_id WHERE j.ro_number = 'RO-TEST-9002' AND version = 2;
-- EXPECT: 1 row, source=ai_proposed, is_unconfirmed=true

-- CHECK 4: partial confirmation (only confirmed_by set, not the others)
-- is rejected by the all-or-nothing CHECK constraint.
DO $$
BEGIN
  INSERT INTO collision.estimate (job_id, version, source, draft_content, confirmed_by, created_by)
  SELECT id, 3, 'ai_proposed', '{"lines": []}'::jsonb, 'partial_confirm_attempt', 'test_harness'
  FROM collision.job WHERE ro_number = 'RO-TEST-9002';
  RAISE EXCEPTION 'CHECK 4 FAILED: partial confirmation should have been rejected';
EXCEPTION WHEN check_violation THEN
  RAISE NOTICE 'CHECK 4 PASSED: partial confirmation rejected by all-or-nothing CHECK';
END $$;

-- CHECK 5: (job_id, version) uniqueness enforced.
DO $$
BEGIN
  INSERT INTO collision.estimate (job_id, version, source, draft_content, confirmed_content, confirmed_by, confirmed_at, created_by)
  SELECT id, 1, 'manual', '{}'::jsonb, '{}'::jsonb, 'x', now(), 'test_harness'
  FROM collision.job WHERE ro_number = 'RO-TEST-9002';
  RAISE EXCEPTION 'CHECK 5 FAILED: duplicate (job_id, version) should have been rejected';
EXCEPTION WHEN unique_violation THEN
  RAISE NOTICE 'CHECK 5 PASSED: (job_id, version) uniqueness enforced';
END $$;

-- CHECK 6: collision_app can SELECT and INSERT, but NOT UPDATE (append-only
-- by design — versions, not mutation).
SET ROLE collision_app;
SELECT count(*) AS visible_estimates FROM collision.estimate e
JOIN collision.job j ON j.id = e.job_id WHERE j.ro_number = 'RO-TEST-9002';
-- EXPECT: 2

INSERT INTO collision.estimate (job_id, version, source, draft_content, confirmed_content, confirmed_by, confirmed_at, created_by)
SELECT id, 4, 'manual', '{"lines": []}'::jsonb, '{"lines": []}'::jsonb, 'collision_app_test', now(), 'collision_app_test'
FROM collision.job WHERE ro_number = 'RO-TEST-9002';
-- EXPECT: succeeds (INSERT granted)

DO $$
BEGIN
  UPDATE collision.estimate SET confirmed_by = 'tampered' WHERE version = 1;
  RAISE EXCEPTION 'CHECK 6b FAILED: collision_app should not be able to UPDATE collision.estimate';
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'CHECK 6b PASSED: collision_app blocked from UPDATE on collision.estimate';
END $$;
RESET ROLE;

SELECT 'ALL CHECKS COMPLETED — CHECK 1 shows manual/confirmed, CHECK 3 shows ai_proposed/unconfirmed, CHECK 2/4/5/6b all PASSED notices' AS summary;

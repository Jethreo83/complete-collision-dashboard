-- Verification harness for migration 008 (collision.job status
-- forward-only trigger). Same discipline as prior verify scripts:
-- prove real trigger behavior by actually attempting illegal
-- transitions and confirming they're rejected, not by reading the DDL.

DO $$
DECLARE
  v_person_id   BIGINT;
  v_customer_id BIGINT;
  v_vehicle_id  BIGINT;
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'TransitionOwner', 'test.transitionowner@example.com', 'test_harness')
  RETURNING id INTO v_person_id;

  INSERT INTO collision.customer (person_id, source, created_by)
  VALUES (v_person_id, 'walk_in', 'test_harness')
  RETURNING id INTO v_customer_id;

  INSERT INTO collision.vehicle (vin, make, model, year, customer_id, created_by)
  VALUES ('TESTVIN0000000004', 'Mazda', 'CX-5', 2020, v_customer_id, 'test_harness')
  RETURNING id INTO v_vehicle_id;

  INSERT INTO collision.job (ro_number, vehicle_id, customer_id, site, category, status, created_by, updated_by)
  VALUES ('RO-TEST-9004', v_vehicle_id, v_customer_id, 'South', 'collision', 'undecided', 'test_harness', 'test_harness');
END $$;

-- CHECK 1: a legal forward transition (undecided -> came_in) succeeds.
UPDATE collision.job SET status = 'came_in', updated_by = 'test_harness' WHERE ro_number = 'RO-TEST-9004';
SELECT status FROM collision.job WHERE ro_number = 'RO-TEST-9004';
-- EXPECT: came_in

-- CHECK 2: a legal skip-ahead forward transition (came_in -> bodywork,
-- skipping estimate/teardown/waiting_on_parts) succeeds — the handoff's
-- sequence is a typical path, not a mandatory-every-step machine.
UPDATE collision.job SET status = 'bodywork', updated_by = 'test_harness' WHERE ro_number = 'RO-TEST-9004';
SELECT status FROM collision.job WHERE ro_number = 'RO-TEST-9004';
-- EXPECT: bodywork

-- CHECK 3: a backward transition (bodywork -> came_in) is rejected by
-- the trigger.
DO $$
BEGIN
  UPDATE collision.job SET status = 'came_in', updated_by = 'test_harness' WHERE ro_number = 'RO-TEST-9004';
  RAISE EXCEPTION 'CHECK 3 FAILED: backward transition should have been rejected';
EXCEPTION WHEN OTHERS THEN
  IF SQLERRM LIKE '%backward status transition%' THEN
    RAISE NOTICE 'CHECK 3 PASSED: backward transition rejected (%)', SQLERRM;
  ELSE
    RAISE EXCEPTION 'CHECK 3 FAILED WITH UNEXPECTED ERROR: %', SQLERRM;
  END IF;
END $$;

-- CHECK 4: status is unchanged after the rejected attempt (still bodywork).
SELECT status FROM collision.job WHERE ro_number = 'RO-TEST-9004';
-- EXPECT: bodywork (unchanged from CHECK 2)

-- CHECK 5: a no-op transition (bodywork -> bodywork) is rejected.
DO $$
BEGIN
  UPDATE collision.job SET status = 'bodywork', updated_by = 'test_harness' WHERE ro_number = 'RO-TEST-9004';
  RAISE EXCEPTION 'CHECK 5 FAILED: no-op transition should have been rejected';
EXCEPTION WHEN OTHERS THEN
  IF SQLERRM LIKE '%no-op status transition%' THEN
    RAISE NOTICE 'CHECK 5 PASSED: no-op transition rejected (%)', SQLERRM;
  ELSE
    RAISE EXCEPTION 'CHECK 5 FAILED WITH UNEXPECTED ERROR: %', SQLERRM;
  END IF;
END $$;

-- CHECK 6: an unrelated UPDATE that doesn't touch status at all is
-- completely unaffected by the trigger (proves the "OF status" scoping
-- actually works, not just the WHEN clause I removed).
UPDATE collision.job SET updated_at = now(), updated_by = 'unrelated_update_test' WHERE ro_number = 'RO-TEST-9004';
SELECT status, updated_by FROM collision.job WHERE ro_number = 'RO-TEST-9004';
-- EXPECT: status still bodywork, updated_by = unrelated_update_test — proves
-- non-status updates are never touched by this trigger

-- CHECK 7: reaching the final state (marketing) and confirming the
-- forward run all the way through works end to end.
UPDATE collision.job SET status = 'marketing', updated_by = 'test_harness' WHERE ro_number = 'RO-TEST-9004';
SELECT status FROM collision.job WHERE ro_number = 'RO-TEST-9004';
-- EXPECT: marketing

-- CHECK 8: collision_app (the actual app role) is subject to the same
-- trigger — not just neondb_owner.
SET ROLE collision_app;
DO $$
BEGIN
  UPDATE collision.job SET status = 'undecided', updated_by = 'collision_app_test' WHERE ro_number = 'RO-TEST-9004';
  RAISE EXCEPTION 'CHECK 8 FAILED: collision_app should also be blocked from a backward transition';
EXCEPTION WHEN OTHERS THEN
  IF SQLERRM LIKE '%backward status transition%' THEN
    RAISE NOTICE 'CHECK 8 PASSED: collision_app blocked from backward transition by the same trigger';
  ELSE
    RAISE EXCEPTION 'CHECK 8 FAILED WITH UNEXPECTED ERROR: %', SQLERRM;
  END IF;
END $$;
RESET ROLE;

SELECT 'ALL CHECKS COMPLETED — CHECK 1/2/7 show forward+skip-ahead succeed, CHECK 3/5/8 PASSED rejection notices, CHECK 4 shows state unchanged after rejection, CHECK 6 shows unrelated updates unaffected' AS summary;

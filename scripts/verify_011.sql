-- Verification harness for migration 011 (collision.payment +
-- collision.job_payment_summary view). Same discipline as
-- verify_001-010: verify by actually inserting rows and observing real
-- behavior under the collision_app role, not just checking catalog
-- objects exist.

DO $$
DECLARE
  v_person_id   BIGINT;
  v_customer_id BIGINT;
  v_vehicle_id  BIGINT;
  v_site_id     BIGINT;
  v_job_id      BIGINT;
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'Payment011', 'test.payment011@example.com', 'test_harness')
  RETURNING id INTO v_person_id;

  INSERT INTO collision.customer (person_id, source, created_by)
  VALUES (v_person_id, 'walk_in', 'test_harness')
  RETURNING id INTO v_customer_id;

  INSERT INTO collision.vehicle (vin, make, model, year, customer_id, created_by)
  VALUES ('TESTVIN011000001', 'Test', 'Model011', 2021, v_customer_id, 'test_harness')
  RETURNING id INTO v_vehicle_id;

  INSERT INTO collision.site (name, created_by)
  VALUES ('Test Site 011', 'test_harness')
  RETURNING id INTO v_site_id;

  INSERT INTO collision.job (
    ro_number, vehicle_id, customer_id, site_id, category, status,
    gross_revenue, created_by, updated_by
  ) VALUES (
    'RO-TEST-9011', v_vehicle_id, v_customer_id, v_site_id, 'collision', 'undecided',
    1000.00, 'test_harness', 'test_harness'
  ) RETURNING id INTO v_job_id;

  CREATE TEMP TABLE _verify_011_job_id (job_id BIGINT);
  INSERT INTO _verify_011_job_id VALUES (v_job_id);
END $$;

GRANT SELECT ON _verify_011_job_id TO collision_app;

-- CHECK 1: no payments yet -- job_payment_summary shows 0/0/NULL for a
-- job with zero payment rows (LEFT JOIN + COALESCE working correctly,
-- not silently omitting the job from the view).
SELECT s.total_collected, s.payment_count, s.last_payment_at
FROM collision.job_payment_summary s, _verify_011_job_id v
WHERE s.job_id = v.job_id;
-- EXPECT: 0, 0, (null)

-- CHECK 2: collision_app can INSERT a 'manual' payment (no
-- external_transaction_id required for non-authorize_net sources).
SET ROLE collision_app;
INSERT INTO collision.payment (job_id, source, amount, created_by)
SELECT job_id, 'manual', 250.00, 'collision_app_test'
FROM _verify_011_job_id;
RESET ROLE;

SELECT s.total_collected, s.payment_count
FROM collision.job_payment_summary s, _verify_011_job_id v
WHERE s.job_id = v.job_id;
-- EXPECT: 250.00, 1

-- CHECK 3: a second payment (different source) accumulates correctly
-- in the summary view (real SUM/count, not a stored/stale total).
SET ROLE collision_app;
INSERT INTO collision.payment (job_id, source, external_transaction_id, amount, created_by)
SELECT job_id, 'insurer_eft', 'EFT-TEST-011', 500.00, 'collision_app_test'
FROM _verify_011_job_id;
RESET ROLE;

SELECT s.total_collected, s.payment_count
FROM collision.job_payment_summary s, _verify_011_job_id v
WHERE s.job_id = v.job_id;
-- EXPECT: 750.00, 2

-- CHECK 4: the CHECK constraint genuinely rejects an authorize_net
-- payment with no external_transaction_id (not just documented, but
-- enforced) -- must fail with a check_violation, not silently succeed.
DO $$
DECLARE
  v_failed BOOLEAN := false;
BEGIN
  SET ROLE collision_app;
  BEGIN
    INSERT INTO collision.payment (job_id, source, amount, created_by)
    SELECT job_id, 'authorize_net', 100.00, 'collision_app_test'
    FROM _verify_011_job_id;
  EXCEPTION WHEN check_violation THEN
    v_failed := true;
  END;
  RESET ROLE;

  IF NOT v_failed THEN
    RAISE EXCEPTION 'CHECK 4 FAILED: an authorize_net payment with no external_transaction_id was accepted';
  END IF;
END $$;

SELECT 'CHECK 4 PASSED: authorize_net payment without external_transaction_id genuinely rejected' AS check_4_result;

-- CHECK 5: append-only is genuinely enforced -- collision_app cannot
-- UPDATE a payment row it just inserted (financial record, same
-- philosophy as job_event/cost_entry/estimate).
DO $$
DECLARE
  v_failed BOOLEAN := false;
BEGIN
  SET ROLE collision_app;
  BEGIN
    UPDATE collision.payment SET amount = 1.00
    WHERE job_id = (SELECT job_id FROM _verify_011_job_id) AND source = 'manual';
  EXCEPTION WHEN insufficient_privilege OR raise_exception THEN
    v_failed := true;
  END;
  RESET ROLE;

  IF NOT v_failed THEN
    RAISE EXCEPTION 'CHECK 5 FAILED: collision_app was able to UPDATE an existing collision.payment row';
  END IF;
END $$;

SELECT 'CHECK 5 PASSED: collision.payment genuinely immutable under collision_app (UPDATE blocked)' AS check_5_result;

-- CHECK 6: same for DELETE (append-only via REVOKE, not just the
-- forbid-mutation trigger -- collision_app has no DELETE grant at all).
DO $$
DECLARE
  v_failed BOOLEAN := false;
BEGIN
  SET ROLE collision_app;
  BEGIN
    DELETE FROM collision.payment
    WHERE job_id = (SELECT job_id FROM _verify_011_job_id) AND source = 'manual';
  EXCEPTION WHEN insufficient_privilege OR raise_exception THEN
    v_failed := true;
  END;
  RESET ROLE;

  IF NOT v_failed THEN
    RAISE EXCEPTION 'CHECK 6 FAILED: collision_app was able to DELETE a collision.payment row';
  END IF;
END $$;

SELECT 'CHECK 6 PASSED: collision.payment genuinely immutable under collision_app (DELETE blocked)' AS check_6_result;

-- Cleanup: collision.payment's forbid-mutation trigger fires for EVERY
-- role, not just collision_app (that's the actual guarantee -- a true
-- immutable audit trail, not just a collision_app-specific
-- restriction) -- so even this privileged connecting role must
-- temporarily disable the trigger to remove test rows, same as a real
-- admin correction would require. Re-enabled immediately after.
ALTER TABLE collision.payment DISABLE TRIGGER trg_payment_forbid_delete;
DELETE FROM collision.payment WHERE job_id = (SELECT job_id FROM _verify_011_job_id);
ALTER TABLE collision.payment ENABLE TRIGGER trg_payment_forbid_delete;
DELETE FROM collision.job WHERE id = (SELECT job_id FROM _verify_011_job_id);
DELETE FROM collision.site WHERE name = 'Test Site 011';
DELETE FROM collision.vehicle WHERE vin = 'TESTVIN011000001';
DELETE FROM collision.customer WHERE person_id = (SELECT id FROM platform.person WHERE email_normalized = 'test.payment011@example.com');
DELETE FROM platform.person WHERE email_normalized = 'test.payment011@example.com';

DROP TABLE _verify_011_job_id;

SELECT 'ALL CHECKS COMPLETED' AS summary;

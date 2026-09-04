-- Verification harness for migration 001 (collision.customer + RLS) — same
-- discipline as VLS verify_004.sql and elektrica verify_001.sql. Verify by
-- actually switching role and querying, not by reading the policy
-- definition.
--
-- RUN against staging 2026-09-04 — all 6 checks passed by direct query
-- output (see WORKLOG.md for the full transcript). Companion to
-- migrations/001_collision_customer.sql, now applied to production.

DO $$
DECLARE
  v_person_customer_id BIGINT;    -- has a collision.customer row -> visible to collision_app
  v_person_no_customer_id BIGINT; -- no collision.customer row -> invisible to collision_app
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'CustomerPerson', 'test.customer@example.com', 'test_harness')
  RETURNING id INTO v_person_customer_id;

  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'NonCustomerPerson', 'test.noncustomer@example.com', 'test_harness')
  RETURNING id INTO v_person_no_customer_id;

  INSERT INTO collision.customer (person_id, source, created_by)
  VALUES (v_person_customer_id, 'walk_in', 'test_harness');

  RAISE NOTICE 'person_customer_id=% person_no_customer_id=%', v_person_customer_id, v_person_no_customer_id;
END $$;

-- CHECK 1: as table owner (FORCE RLS on platform.person, set in VLS
-- migration 004, applies even to the owner unless it owns the table).
-- Confirms both person rows exist from the privileged connection.
SELECT id, first_name, last_name FROM platform.person WHERE last_name IN ('CustomerPerson', 'NonCustomerPerson') ORDER BY id;
-- EXPECT: 2 rows

-- CHECK 2: as collision_app, should see ONLY the person with a
-- collision.customer row.
SET ROLE collision_app;
SELECT id, first_name, last_name FROM platform.person WHERE last_name IN ('CustomerPerson', 'NonCustomerPerson') ORDER BY id;
-- EXPECT: 1 row — CustomerPerson only. NonCustomerPerson must be ABSENT,
-- not flagged, not null-masked — genuinely absent from the result set.
RESET ROLE;

-- CHECK 3: collision_app cannot INSERT into platform.person directly (must
-- go through the identity service, same rule as vls_app / elektrica_app).
SET ROLE collision_app;
DO $$
BEGIN
  INSERT INTO platform.person (first_name, last_name, created_by)
  VALUES ('Should', 'Fail', 'collision_app');
  RAISE EXCEPTION 'CHECK 3 FAILED: collision_app should not be able to INSERT into platform.person';
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'CHECK 3 PASSED: collision_app blocked from INSERT on platform.person';
END $$;
RESET ROLE;

-- CHECK 4: platform_identity_service (created in VLS migration 004) sees
-- everything, including Collision's customers — confirms the shared
-- identity service role's bypass policy is not scoped to VLS/Elektrica
-- only.
SET ROLE platform_identity_service;
SELECT id, first_name, last_name FROM platform.person WHERE last_name IN ('CustomerPerson', 'NonCustomerPerson') ORDER BY id;
-- EXPECT: 2 rows
RESET ROLE;

-- CHECK 5: collision_app CAN read/write collision.customer — RLS is scoped
-- to platform.person only, not collision's own schema.
SET ROLE collision_app;
SELECT person_id, source FROM collision.customer WHERE source = 'walk_in' AND person_id IN (
  SELECT id FROM platform.person WHERE last_name = 'CustomerPerson'
);
-- EXPECT: 1 row
RESET ROLE;

-- CHECK 6: collision.customer enforces one row per person.
DO $$
BEGIN
  INSERT INTO collision.customer (person_id, created_by)
  SELECT id, 'test_harness' FROM platform.person WHERE last_name = 'CustomerPerson';
  RAISE EXCEPTION 'CHECK 6 FAILED: duplicate customer row for same person_id should have been rejected';
EXCEPTION WHEN unique_violation THEN
  RAISE NOTICE 'CHECK 6 PASSED: customer_one_row_per_person constraint enforced';
END $$;

SELECT 'ALL CHECKS COMPLETED — CHECK 2 must show exactly 1 row (CustomerPerson)' AS summary;

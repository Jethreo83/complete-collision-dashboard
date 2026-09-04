-- Verification harness for migration 004 (collision.staff_user role enum
-- + provisioning shape only — NO permission enforcement, by design; see
-- migration file header). Same discipline as verify_001/002/003.sql.

DO $$
DECLARE
  v_owner_person_id   BIGINT;
  v_owner_staff_id    BIGINT;
  v_recept_person_id  BIGINT;
  v_recept_staff_id   BIGINT;
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'OwnerStaff', 'test.ownerstaff@example.com', 'test_harness')
  RETURNING id INTO v_owner_person_id;

  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'ReceptionistStaff', 'test.receptionist@example.com', 'test_harness')
  RETURNING id INTO v_recept_person_id;

  -- Bootstrap case: first staff_user has no provisioner (nullable FK).
  INSERT INTO collision.staff_user (person_id, role, google_email, created_by, updated_by)
  VALUES (v_owner_person_id, 'owner', 'owner@example-shop.com', 'test_harness', 'test_harness')
  RETURNING id INTO v_owner_staff_id;

  -- Second staff_user, provisioned BY the owner (admin-provisioned per
  -- ADR-001 §4 -- no self-signup).
  INSERT INTO collision.staff_user (person_id, role, google_email, provisioned_by_staff_user_id, created_by, updated_by)
  VALUES (v_recept_person_id, 'receptionist', 'receptionist@example-shop.com', v_owner_staff_id, 'test_harness', 'test_harness')
  RETURNING id INTO v_recept_staff_id;

  RAISE NOTICE 'owner_staff_id=% receptionist_staff_id=%', v_owner_staff_id, v_recept_staff_id;
END $$;

-- CHECK 1: both roles exist with correct enum values.
SELECT role, google_email, active FROM collision.staff_user
WHERE google_email IN ('owner@example-shop.com', 'receptionist@example-shop.com')
ORDER BY role;
-- EXPECT: 2 rows — owner and receptionist, both active=true (default)

-- CHECK 2: provisioning chain is recorded (receptionist provisioned by owner).
SELECT su_recept.google_email AS receptionist_email, su_owner.google_email AS provisioned_by_email
FROM collision.staff_user su_recept
JOIN collision.staff_user su_owner ON su_owner.id = su_recept.provisioned_by_staff_user_id
WHERE su_recept.role = 'receptionist';
-- EXPECT: 1 row, provisioned_by_email = owner@example-shop.com

-- CHECK 3: one staff_user row per person is enforced.
DO $$
BEGIN
  INSERT INTO collision.staff_user (person_id, role, google_email, created_by, updated_by)
  SELECT person_id, 'manager', 'duplicate@example-shop.com', 'test_harness', 'test_harness'
  FROM collision.staff_user WHERE role = 'owner';
  RAISE EXCEPTION 'CHECK 3 FAILED: duplicate staff_user for same person_id should have been rejected';
EXCEPTION WHEN unique_violation THEN
  RAISE NOTICE 'CHECK 3 PASSED: staff_user_one_row_per_person constraint enforced';
END $$;

-- CHECK 4: google_email uniqueness is enforced.
DO $$
DECLARE
  v_new_person_id BIGINT;
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'DuplicateEmailStaff', 'test.dupemail@example.com', 'test_harness')
  RETURNING id INTO v_new_person_id;

  INSERT INTO collision.staff_user (person_id, role, google_email, created_by, updated_by)
  VALUES (v_new_person_id, 'manager', 'owner@example-shop.com', 'test_harness', 'test_harness');
  RAISE EXCEPTION 'CHECK 4 FAILED: duplicate google_email should have been rejected';
EXCEPTION WHEN unique_violation THEN
  RAISE NOTICE 'CHECK 4 PASSED: google_email uniqueness enforced';
END $$;

-- CHECK 5: collision_app can read/write staff_user (SELECT/INSERT/UPDATE
-- granted, no per-role restriction — confirming the ABSENCE of
-- role-scoped enforcement is deliberate, per the migration's "stop
-- short of wiring real permission checks" scope).
SET ROLE collision_app;
SELECT role, google_email FROM collision.staff_user WHERE role = 'receptionist';
-- EXPECT: 1 row -- collision_app sees it, no role-based visibility
-- restriction exists yet (that's the explicitly deferred piece, not a bug)
UPDATE collision.staff_user SET updated_by = 'collision_app_test' WHERE role = 'receptionist';
SELECT updated_by FROM collision.staff_user WHERE role = 'receptionist';
-- EXPECT: updated_by = 'collision_app_test' -- collision_app CAN update any
-- staff_user row today, confirming no permission wiring exists yet
RESET ROLE;

SELECT 'ALL CHECKS COMPLETED — CHECK 1 shows 2 rows (owner, receptionist), CHECK 2 shows provisioning chain, CHECK 3/4 PASSED notices, CHECK 5 confirms no role-based restriction exists yet (by design, deferred)' AS summary;

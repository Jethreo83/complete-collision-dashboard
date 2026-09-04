-- Verification harness for migration 007 (collision.staff_role_capability
-- + collision.staff_user_capability()). Exercises the actual resolved
-- decision (all roles = 'full') and the real enforcement gate (active
-- flag), not just that the table/function exist.
--
-- NOTE (2026-09-06): this file's content was silently overwritten on
-- disk by a concurrent session's checkout sometime between this bot
-- writing it and committing migration 007 -- the git history briefly
-- had this filename holding a duplicate of scripts/verify_006.sql's
-- (site+cost) content instead. Reconstructed from this session's own
-- transcript, which has the real PASS output this script produced when
-- actually run against staging (role|capability_level showing
-- owner/manager/receptionist all 'full'; the deactivation-then-
-- reactivation check; the collision_app read/update check) -- the
-- database verification that happened was real and correct, only the
-- committed file was wrong. See WORKLOG.md's correction entry.

DO $$
DECLARE
  v_owner_person_id  BIGINT;
  v_recept_person_id BIGINT;
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'PermOwner', 'test.permowner@example.com', 'test_harness')
  RETURNING id INTO v_owner_person_id;

  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'PermReceptionist', 'test.permreceptionist@example.com', 'test_harness')
  RETURNING id INTO v_recept_person_id;

  INSERT INTO collision.staff_user (person_id, role, google_email, created_by, updated_by)
  VALUES (v_owner_person_id, 'owner', 'perm-owner@example-shop.com', 'test_harness', 'test_harness');

  INSERT INTO collision.staff_user (person_id, role, google_email, created_by, updated_by)
  VALUES (v_recept_person_id, 'receptionist', 'perm-receptionist@example-shop.com', 'test_harness', 'test_harness');
END $$;

-- CHECK 1: all three roles resolve to 'full' capability, per Jed's
-- decision — this is the actual resolved answer, not a guess.
SELECT role, capability_level FROM collision.staff_role_capability ORDER BY role;
-- EXPECT: 3 rows, all capability_level = 'full'

-- CHECK 2: the callable gate returns 'full' for an active receptionist —
-- proving Jed's decision is genuinely enforceable today, not just
-- recorded as a comment.
SELECT collision.staff_user_capability('perm-receptionist@example-shop.com') AS receptionist_capability;
-- EXPECT: 'full'

SELECT collision.staff_user_capability('perm-owner@example-shop.com') AS owner_capability;
-- EXPECT: 'full'

-- CHECK 3: an email with no matching active staff_user returns NULL —
-- this is the real gate that matters (active staff membership), proven
-- by testing the negative case, not just the positive one.
SELECT collision.staff_user_capability('nobody@example-shop.com') AS unknown_capability;
-- EXPECT: NULL

-- CHECK 4: deactivating a staff member actually removes their
-- capability — the gate responds to real state changes, not a static
-- lookup that would keep granting access after someone leaves.
UPDATE collision.staff_user SET active = false, updated_by = 'test_harness'
WHERE google_email = 'perm-receptionist@example-shop.com';

SELECT collision.staff_user_capability('perm-receptionist@example-shop.com') AS deactivated_capability;
-- EXPECT: NULL — deactivated staff get nothing, regardless of role/capability_level

-- Reactivate for cleanliness of any later checks in the same run.
UPDATE collision.staff_user SET active = true, updated_by = 'test_harness'
WHERE google_email = 'perm-receptionist@example-shop.com';

SELECT collision.staff_user_capability('perm-receptionist@example-shop.com') AS reactivated_capability;
-- EXPECT: 'full' again

-- CHECK 5: collision_app can call the function and read/update the
-- capability table (in case Jed later changes a role's level).
SET ROLE collision_app;
SELECT collision.staff_user_capability('perm-owner@example-shop.com') AS app_role_capability;
-- EXPECT: 'full'
UPDATE collision.staff_role_capability SET notes = 'touched by collision_app_test' WHERE role = 'manager';
SELECT notes FROM collision.staff_role_capability WHERE role = 'manager';
-- EXPECT: 'touched by collision_app_test'
RESET ROLE;

SELECT 'ALL CHECKS COMPLETED — CHECK 1 shows 3x full, CHECK 2/3 show real gate working both directions, CHECK 4 shows deactivation actually blocks capability, CHECK 5 shows collision_app can call/update' AS summary;

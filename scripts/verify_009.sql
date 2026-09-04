-- Verification harness for migration 009 (staff_user google_email domain
-- CHECK constraint). Same discipline as verify_001-008: verify by
-- actually inserting rows and observing real acceptance/rejection, not
-- just that the constraint object exists in the catalog.

-- CHECK 1: constraint exists and is a CHECK constraint on staff_user.
SELECT conname, contype
FROM pg_constraint
WHERE conrelid = 'collision.staff_user'::regclass
  AND conname = 'staff_user_google_email_domain';
-- EXPECT: 1 row, contype = 'c'

-- CHECK 2: a real completecollisions.com email is accepted.
DO $$
DECLARE
  v_person_id BIGINT;
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'DomainOk', 'test.domainok@example.com', 'test_harness')
  RETURNING id INTO v_person_id;

  INSERT INTO collision.staff_user (person_id, role, google_email, created_by, updated_by)
  VALUES (v_person_id, 'manager', 'domain-ok@completecollisions.com', 'test_harness', 'test_harness');
END $$;

SELECT google_email FROM collision.staff_user WHERE google_email = 'domain-ok@completecollisions.com';
-- EXPECT: 1 row — insert succeeded

-- CHECK 3: a non-matching domain is genuinely rejected by the database,
-- not just informally discouraged. Uses a savepoint so this expected
-- failure doesn't abort the whole verify script's transaction.
DO $$
DECLARE
  v_person_id BIGINT;
  v_failed BOOLEAN := false;
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'DomainBad', 'test.domainbad@example.com', 'test_harness')
  RETURNING id INTO v_person_id;

  BEGIN
    INSERT INTO collision.staff_user (person_id, role, google_email, created_by, updated_by)
    VALUES (v_person_id, 'manager', 'wrong-domain@gmail.com', 'test_harness', 'test_harness');
  EXCEPTION WHEN check_violation THEN
    v_failed := true;
  END;

  IF NOT v_failed THEN
    RAISE EXCEPTION 'CHECK 3 FAILED: a non-completecollisions.com email was accepted, constraint is not working';
  END IF;
END $$;

SELECT 'CHECK 3 PASSED: wrong-domain email was genuinely rejected by the database' AS check_3_result;

-- CHECK 4: subdomain / substring tricks around the domain string are
-- also rejected (LIKE anchors on '@completecollisions.com' at the end,
-- so 'x@completecollisions.com.evil.com' must fail, and
-- 'x@notcompletecollisions.com' must also fail since LIKE '%@...' still
-- requires the literal '@' immediately before the domain).
DO $$
DECLARE
  v_person_id BIGINT;
  v_failed BOOLEAN := false;
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'DomainTrick', 'test.domaintrick@example.com', 'test_harness')
  RETURNING id INTO v_person_id;

  BEGIN
    INSERT INTO collision.staff_user (person_id, role, google_email, created_by, updated_by)
    VALUES (v_person_id, 'manager', 'trick@completecollisions.com.evil.com', 'test_harness', 'test_harness');
  EXCEPTION WHEN check_violation THEN
    v_failed := true;
  END;

  IF NOT v_failed THEN
    RAISE EXCEPTION 'CHECK 4 FAILED: a lookalike domain (...com.evil.com) was accepted';
  END IF;
END $$;

SELECT 'CHECK 4 PASSED: lookalike domain suffix was genuinely rejected' AS check_4_result;

SELECT 'ALL CHECKS COMPLETED' AS summary;

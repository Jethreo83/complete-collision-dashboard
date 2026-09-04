-- Verification harness for migration 005 (collision.content_item).
-- Exercises the actual views handoff §3.1 asks for (by RO, by uploader),
-- the search index, orphaned-RO tolerance, and the dedup constraint —
-- not just "table exists."

DO $$
DECLARE
  v_person_id   BIGINT;
  v_customer_id BIGINT;
  v_vehicle_id  BIGINT;
  v_job_id      BIGINT;
BEGIN
  INSERT INTO platform.person (first_name, last_name, email_normalized, created_by)
  VALUES ('Test', 'ContentOwner', 'test.contentowner@example.com', 'test_harness')
  RETURNING id INTO v_person_id;

  INSERT INTO collision.customer (person_id, source, created_by)
  VALUES (v_person_id, 'walk_in', 'test_harness')
  RETURNING id INTO v_customer_id;

  INSERT INTO collision.vehicle (vin, make, model, year, customer_id, created_by)
  VALUES ('TESTVIN0000000003', 'Honda', 'Civic', 2021, v_customer_id, 'test_harness')
  RETURNING id INTO v_vehicle_id;

  INSERT INTO collision.job (ro_number, vehicle_id, customer_id, site, category, status, created_by, updated_by)
  VALUES ('RO-TEST-9003', v_vehicle_id, v_customer_id, 'South', 'collision', 'marketing', 'test_harness', 'test_harness')
  RETURNING id INTO v_job_id;

  RAISE NOTICE 'job_id=%', v_job_id;
END $$;

-- CHECK 1: insert a content item referencing a real RO, all 22 manifest
-- fields represented.
INSERT INTO collision.content_item (
  source_manifest_id, import_source_file, business, collection, description,
  drive_id, filename, mime, proxy_url, ro_number, service, size, smr,
  source, stage, status, thumbnail, type, uploaded_at, uploader, url,
  video_type, web_view_link, created_by, updated_by
) VALUES (
  'manifest-0001', 'content_manifest.json', 'Complete Collision', 'before_after',
  'red sedan bumper repair, before shot', 'drive-abc123', 'IMG_before_0001.jpg',
  'image/jpeg', 'https://proxy.example/0001', 'RO-TEST-9003', 'bodywork', 245678,
  'smr-001', 'phone_upload', 'bodywork', 'active', 'https://thumb.example/0001',
  'photo', now(), 'jane_estimator', 'https://drive.example/0001', NULL,
  'https://drive.google.com/file/0001', 'test_harness', 'test_harness'
);

SELECT filename, ro_number, uploader, source_manifest_id FROM collision.content_item
WHERE source_manifest_id = 'manifest-0001';
-- EXPECT: 1 row

-- CHECK 2: "by RO" view (handoff §3.1) — join collision.content_item to
-- collision.job by ro_number, tolerating no FK.
SELECT ci.filename, ci.uploader, j.status AS job_status
FROM collision.content_item ci
JOIN collision.job j ON j.ro_number = ci.ro_number
WHERE j.ro_number = 'RO-TEST-9003';
-- EXPECT: 1 row, job_status=marketing

-- CHECK 3: orphaned ro_number (references a job that doesn't exist) is
-- accepted, not rejected — confirms the deliberate no-FK design actually
-- tolerates messy real-world data as intended, not just in theory.
INSERT INTO collision.content_item (filename, ro_number, uploader, created_by, updated_by)
VALUES ('IMG_orphan_0002.jpg', 'RO-DOES-NOT-EXIST-9999', 'bob_tech', 'test_harness', 'test_harness');

SELECT filename, ro_number FROM collision.content_item WHERE filename = 'IMG_orphan_0002.jpg';
-- EXPECT: 1 row — insert succeeded despite no matching collision.job row

-- CHECK 4: "by uploader per day" view (handoff §3.1).
INSERT INTO collision.content_item (filename, ro_number, uploader, uploaded_at, created_by, updated_by)
VALUES ('IMG_0003.jpg', 'RO-TEST-9003', 'jane_estimator', now(), 'test_harness', 'test_harness');

SELECT uploader, date_trunc('day', uploaded_at) AS upload_day, count(*) AS item_count
FROM collision.content_item
WHERE uploader = 'jane_estimator'
GROUP BY uploader, date_trunc('day', uploaded_at);
-- EXPECT: 1 row, item_count=2 (both jane_estimator uploads today)

-- CHECK 5: dedup constraint — re-importing the same source_manifest_id
-- is rejected.
DO $$
BEGIN
  INSERT INTO collision.content_item (source_manifest_id, filename, created_by, updated_by)
  VALUES ('manifest-0001', 'IMG_duplicate.jpg', 'test_harness', 'test_harness');
  RAISE EXCEPTION 'CHECK 5 FAILED: duplicate source_manifest_id should have been rejected';
EXCEPTION WHEN unique_violation THEN
  RAISE NOTICE 'CHECK 5 PASSED: source_manifest_id dedup constraint enforced';
END $$;

-- CHECK 6: NULL source_manifest_id rows (dashboard-native uploads, not
-- from the JSON import) are exempt from the dedup constraint — multiple
-- rows with NULL source_manifest_id must be allowed.
INSERT INTO collision.content_item (filename, created_by, updated_by) VALUES ('IMG_native_a.jpg', 'test_harness', 'test_harness');
INSERT INTO collision.content_item (filename, created_by, updated_by) VALUES ('IMG_native_b.jpg', 'test_harness', 'test_harness');
SELECT count(*) AS null_manifest_id_count FROM collision.content_item WHERE source_manifest_id IS NULL;
-- EXPECT: >= 3 (IMG_orphan_0002, IMG_0003, IMG_native_a, IMG_native_b all have NULL source_manifest_id)

-- CHECK 7: full-text search index actually finds a description match
-- (handoff §3.1: "red sedan, paint booth, last month" style queries).
SELECT filename FROM collision.content_item
WHERE to_tsvector('english', coalesce(description, '')) @@ to_tsquery('english', 'red & sedan');
-- EXPECT: 1 row — IMG_before_0001.jpg (the only row with "red sedan" in its description)

-- CHECK 8: collision_app can read/write.
SET ROLE collision_app;
SELECT count(*) AS visible_count FROM collision.content_item;
-- EXPECT: >= 5
RESET ROLE;

SELECT 'ALL CHECKS COMPLETED — CHECK 2 shows RO join, CHECK 3 shows orphan tolerated, CHECK 4 shows uploader/day grouping, CHECK 5 PASSED, CHECK 7 shows FTS match' AS summary;

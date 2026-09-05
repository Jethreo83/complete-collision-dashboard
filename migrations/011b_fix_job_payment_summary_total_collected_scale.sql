-- 011b_fix_job_payment_summary_total_collected_scale.sql
--
-- FIX, applied to STAGING only (same posture as migration 011 itself --
-- collision.payment/job_payment_summary have not been promoted to
-- production). Found by real execution during this cycle's HTTP smoke
-- test (scripts/_smoke_http_payments.py): a job with zero payments
-- returned total_collected="0" instead of "0.00" over the API.
--
-- ROOT CAUSE: migrations/011's original view used
-- `COALESCE(SUM(p.amount), 0)` -- the bare integer literal 0 has no
-- decimal scale, so Postgres's COALESCE result type/typmod for the
-- zero-row case loses the NUMERIC(12,2) scale that SUM(p.amount) has
-- when rows exist. json/pydantic then serializes that scale-less zero
-- as "0" rather than "0.00", which is a real, user-visible
-- inconsistency (financial figures should never change their apparent
-- precision depending on whether data exists).
--
-- FIX: explicit ::NUMERIC(12,2) cast on the COALESCE result, applied
-- both here (idempotent re-application against staging) and in
-- migrations/011_collision_payment.sql's own source (so a fresh
-- from-scratch apply of 011 doesn't reintroduce this bug) -- migration
-- history is not rewritten (011 is kept as originally numbered; this
-- is a separate corrective file, same discipline as the 006 ROLLBACK
-- pattern), but the CANONICAL migration source in 011 itself is
-- corrected in place since 011 was never promoted to production and no
-- real (non-test) data has ever been committed to collision.payment.
--
-- DROP+CREATE (not CREATE OR REPLACE): Postgres rejects
-- CREATE OR REPLACE VIEW when a column's data type actually changes
-- (numeric -> numeric(12,2) is a real typmod/scale change, not just a
-- cosmetic rename) -- confirmed by real execution
-- ("cannot change data type of view column"). The GRANT on the view is
-- NOT re-lost by this drop+recreate because collision_app's grant is
-- re-issued explicitly below (grants do not survive a DROP VIEW).
DROP VIEW collision.job_payment_summary;

CREATE VIEW collision.job_payment_summary AS
SELECT
  j.id AS job_id,
  j.ro_number,
  COALESCE(SUM(p.amount), 0)::NUMERIC(12,2) AS total_collected,
  count(p.id) AS payment_count,
  max(p.received_at) AS last_payment_at
FROM collision.job j
LEFT JOIN collision.payment p ON p.job_id = j.id
GROUP BY j.id, j.ro_number;

GRANT SELECT ON collision.job_payment_summary TO collision_app;

-- 009_collision_staff_domain_constraint.sql
--
-- Adds the Google Workspace domain restriction that migration 004
-- explicitly deferred: "no CHECK constraint on domain here because the
-- actual domain string is not confirmed in any source document this bot
-- has read, and guessing at it would be exactly the kind of unconfirmed
-- assumption ADR-001's 'PLACEHOLDER' discipline says not to bake into a
-- promoted migration."
--
-- Jed has now confirmed the domain directly (relayed via hermes,
-- 2026-09-06): completecollisions.com. This migration adds the
-- CHECK constraint migration 004 was written to accept once that answer
-- arrived.
--
-- Design note: enforced as a CHECK constraint on google_email itself
-- (must end in '@completecollisions.com'), not as a separate boolean or
-- trigger, since it's a simple, static, always-true business rule with
-- no exceptions described anywhere (no contractor/vendor staff_user rows
-- are described in ADR-001 -- if that ever becomes untrue, this
-- constraint is a straightforward one to relax later).
--
-- Safe to apply now: collision.staff_user has 0 rows in production
-- (confirmed 2026-09-06 immediately before writing this migration, same
-- as every prior migration's safety check) -- no existing row could
-- violate the new constraint.

ALTER TABLE collision.staff_user
  ADD CONSTRAINT staff_user_google_email_domain
  CHECK (google_email LIKE '%@completecollisions.com');

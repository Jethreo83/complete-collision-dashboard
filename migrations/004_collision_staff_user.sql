-- 004_collision_staff_user.sql
--
-- collision.staff_user — role enum + provisioning table shape ONLY, per
-- hermes's 2026-09-04 instruction: "build the safe subset now (role
-- enum, provisioning table shape) without finalizing what a receptionist
-- can actually touch. Stop short of wiring real permission checks until
-- that answer comes back." Receptionist's exact permission boundaries
-- are logged as PENDING for Jed (vls-dashboard docs/OVERNIGHT_DECISIONS.md,
-- per hermes) — NOT decided here, NOT guessed at here.
--
-- Per ADR-001-complete-collision.md §4: "this needs the same staff_user +
-- role pattern already proven in VLS migration 005 (Google Sign-In
-- restricted to the business domain, role enum, admin-provisioned).
-- Recommend three roles at minimum: owner, manager, receptionist."
--
-- IMPORTANT LIMITATION, stated plainly rather than hidden: this bot has
-- NOT read VLS migration 005's actual SQL (out of scope per this bot's
-- standing no-VLS-source-access boundary). Everything below is built
-- from the ADR's prose description of that pattern only ("Google
-- Sign-In restricted to the business domain, role enum,
-- admin-provisioned"), not from copying VLS's real implementation. If
-- VLS migration 005 does something materially different in its actual
-- SQL (constraint names, exact domain-restriction mechanism, additional
-- columns), this file may need reconciling once/if this bot is given
-- permission to read that source directly.
--
-- WHAT THIS MIGRATION DOES:
--   - Defines the role enum (owner/manager/receptionist).
--   - Creates collision.staff_user: one row per staff member, keyed to
--     platform.person (consistent with customer/job/estimate), holding
--     their assigned role and Google-domain-restricted email.
--   - Records who provisioned each staff account and when
--     (admin-provisioned, per ADR-001 §4 — no self-signup).
-- WHAT THIS MIGRATION DELIBERATELY DOES NOT DO:
--   - No RLS policies scoped by role on collision.job/customer/estimate.
--   - No route-guard or application-layer permission logic.
--   - No decision about what a receptionist can read/write vs.
--     manager/owner — that's the exact question logged PENDING for Jed.
-- Wiring real permission checks is explicitly deferred until that answer
-- comes back, per hermes's instruction above.

CREATE TYPE collision.staff_role AS ENUM (
  'owner',
  'manager',
  'receptionist'
);

CREATE TABLE collision.staff_user (
  id                BIGSERIAL PRIMARY KEY,
  person_id         BIGINT NOT NULL REFERENCES platform.person (id),

  role              collision.staff_role NOT NULL,

  -- Google Sign-In restricted to the business domain, per ADR-001 §4.
  -- Stored as the actual email so the sign-in flow can look up/validate
  -- against it; domain restriction itself is an application-layer check
  -- (validate email ends in the business's Google Workspace domain),
  -- not enforced by this column alone -- no CHECK constraint on domain
  -- here because the actual domain string is not confirmed in any
  -- source document this bot has read, and guessing at it would be
  -- exactly the kind of unconfirmed assumption ADR-001's "PLACEHOLDER"
  -- discipline (see elektrica.vehicle for precedent) says not to bake
  -- into a promoted migration.
  google_email      TEXT NOT NULL UNIQUE,

  active            BOOLEAN NOT NULL DEFAULT true,

  -- Admin-provisioned, per ADR-001 §4 ("role enum, admin-provisioned") --
  -- no self-signup path. provisioned_by is a staff_user.id once one
  -- exists to bootstrap from, but the very first row has no prior
  -- staff_user to reference -- nullable to allow that bootstrap case,
  -- with created_by (free text, same convention as every other table in
  -- this schema) always populated regardless.
  provisioned_by_staff_user_id BIGINT REFERENCES collision.staff_user (id),

  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        TEXT NOT NULL,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by        TEXT NOT NULL,

  CONSTRAINT staff_user_one_row_per_person UNIQUE (person_id)
);

CREATE INDEX idx_staff_user_person ON collision.staff_user (person_id);
CREATE INDEX idx_staff_user_role ON collision.staff_user (role);
CREATE INDEX idx_staff_user_active ON collision.staff_user (active) WHERE active;

-- Grants: collision_app can read/write staff_user like its other tables.
-- No role-scoped RLS here -- see "DELIBERATELY DOES NOT DO" above. Any
-- app-layer code reading this table today should treat every row as
-- readable/writable by the same app-level privilege collision_app
-- already has everywhere else in this schema; per-role restriction is
-- the explicitly deferred piece.
GRANT SELECT, INSERT, UPDATE ON collision.staff_user TO collision_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA collision TO collision_app;

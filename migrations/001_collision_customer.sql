-- 001_collision_customer.sql
-- Complete Collision schema bootstrap: collision.customer + RLS on
-- platform.person.
--
-- Per ADR-001-complete-collision.md §5 (build order item 5) and hermes's
-- guidance: "same platform.person cross-schema pattern as vls.client and
-- elektrica.renter." Identical shape to elektrica.renter
-- (migrations/001_elektrica_renter.sql in elektrica-dashboard), itself
-- identical to vls.client (VLS migration 004). No placeholder fields in
-- this file.
--
-- APPLIED to production 2026-09-04, tagged `collision-migration-001`.
-- Sharing the Neon project named "Jocasta Dashboard" (aged-art-92489373,
-- also VLS's project) required Jed's own direct confirmation given this
-- bot's standing "no relationship to VLS/Jocasta" boundary — obtained via
-- a clickable prompt naming VLS explicitly ("Same Neon project as
-- VLS/Elektrica, new `collision` schema"). See WORKLOG.md for the full
-- resolution narrative and verification output.

CREATE SCHEMA IF NOT EXISTS collision;

-- ---------------------------------------------------------------------------
-- collision.customer — Complete Collision's own party table, identical
-- pattern to vls.client / elektrica.renter. A person is visible to
-- collision_app only if a row exists here.
-- ---------------------------------------------------------------------------

CREATE TABLE collision.customer (
  id                BIGSERIAL PRIMARY KEY,
  person_id         BIGINT NOT NULL REFERENCES platform.person (id),

  -- source of the customer relationship — walk-in / insurer-referred /
  -- Elektrica rental customer (cross-business link, ADR-001 §1 Elektrica
  -- Operating Agreement routing rule) / other referral.
  source            TEXT NOT NULL DEFAULT 'walk_in',

  -- Cross-business link: set when this customer's repair originated from
  -- (or is linked to) an Elektrica-rented vehicle, per the Elektrica/
  -- Complete Collision Operating Agreement's "Originating Shop" routing
  -- rule (ADR-001 §1, §7). Nullable — most customers have no Elektrica
  -- link. Stored as a bare reference, not a foreign key, because it points
  -- into elektrica's schema and elektrica.renter's id is not guaranteed
  -- stable/visible cross-schema without an explicit cross-app grant this
  -- migration does not request.
  elektrica_renter_ref BIGINT,

  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        TEXT NOT NULL,

  CONSTRAINT customer_one_row_per_person UNIQUE (person_id)
);

CREATE INDEX idx_customer_person ON collision.customer (person_id);
CREATE INDEX idx_customer_elektrica_ref ON collision.customer (elektrica_renter_ref)
  WHERE elektrica_renter_ref IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Row-level security on platform.person, collision edition. Identical
-- mechanism to VLS migration 004 / elektrica migration 001: a Postgres
-- role per app, collision_app can see a person row only if a matching
-- collision.customer row exists.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collision_app') THEN
    CREATE ROLE collision_app NOLOGIN;
  END IF;
END $$;

GRANT collision_app TO neondb_owner;

GRANT USAGE ON SCHEMA platform TO collision_app;
GRANT SELECT ON platform.person TO collision_app;
GRANT USAGE ON SCHEMA collision TO collision_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA collision TO collision_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA collision TO collision_app;

CREATE POLICY collision_app_sees_own_customers ON platform.person
  FOR SELECT
  TO collision_app
  USING (
    EXISTS (
      SELECT 1 FROM collision.customer c WHERE c.person_id = platform.person.id
    )
  );

-- collision_app may not write new person rows directly — creation goes
-- through the identity service's match-before-create flow, same rule as
-- vls_app and elektrica_app. No INSERT grant to collision_app on
-- platform.person, enforced by the SELECT-only grant above.

-- Note: ALTER DEFAULT PRIVILEGES not set here, matching the VLS/Elektrica
-- precedent — future collision tables need their own GRANT statements in
-- the migration that creates them.

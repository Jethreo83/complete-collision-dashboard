-- 007_collision_staff_permission.sql
--
-- Real permission enforcement for collision.staff_user, per Jed's
-- decision (relayed by hermes, 2026-09-04, logged in vls-dashboard's
-- OVERNIGHT_DECISIONS.md): "treat [receptionist] like an admin role -
-- full access, not restricted." This RESOLVES ADR-001 §6 open item #1
-- (exact receptionist permission boundaries).
--
-- RESULT OF THE DECISION: all three roles (owner, manager, receptionist)
-- get equivalent, full capability. There is no role-based restriction to
-- enforce between them — the "enforcement" that actually matters now is
-- active-staff-membership itself: is this person a currently-active
-- staff_user at all, regardless of role. That is the real, testable gate
-- this migration adds.
--
-- Modeled as data (collision.staff_role_capability), not hardcoded
-- application logic, so a future change of mind (e.g. Jed later decides
-- receptionist SHOULD be restricted after all) is an UPDATE to this
-- table, not a new migration or an app redeploy.
--
-- SCOPE LIMIT, stated plainly: this migration does NOT wire RLS on
-- collision.job/estimate/customer/vehicle/content_item scoped to an
-- authenticated staff identity, because no backend/session-auth
-- mechanism exists yet (README.md: "No backend/API/frontend exists
-- yet") — inventing a session-variable or JWT-claim convention now would
-- be guessing at unbuilt architecture, not enforcing a real decision.
-- What IS built here is the callable capability-check function a future
-- backend will call before allowing any action:
-- collision.staff_user_capability(google_email) — returns the
-- capability level for an active staff member, or NULL for anyone not
-- an active staff_user (wrong email, deactivated account, or never
-- provisioned). This is genuinely enforceable today (verified below by
-- flipping active on and off and re-checking), even without a backend,
-- because it's a pure function over already-real data.

CREATE TABLE collision.staff_role_capability (
  role              collision.staff_role PRIMARY KEY,
  capability_level  TEXT NOT NULL,  -- 'full' today for all three roles,
                                     -- per Jed's decision. Free text (not
                                     -- an enum) deliberately: capability
                                     -- levels are exactly the kind of
                                     -- thing likely to gain more values
                                     -- later (e.g. 'read_only',
                                     -- 'financial_only') once real
                                     -- feature-level permissions are
                                     -- designed — an enum would need a
                                     -- migration for every new level,
                                     -- free text does not.
  notes             TEXT
);

INSERT INTO collision.staff_role_capability (role, capability_level, notes) VALUES
  ('owner', 'full', 'Owner: full access, unchanged from original design.'),
  ('manager', 'full', 'Manager: full access, unchanged from original design (ADR-001 §4 recommended "operational, maybe financial" but nothing has since restricted this).'),
  ('receptionist', 'full', 'Receptionist: Jed''s explicit decision 2026-09-04 (relayed by hermes, logged in vls-dashboard OVERNIGHT_DECISIONS.md) — "treat like an admin role, full access, not restricted." Resolves ADR-001 §6 open item #1.');

-- ---------------------------------------------------------------------------
-- collision.staff_user_capability — the real, callable gate. Returns the
-- capability_level string for an ACTIVE staff member matching the given
-- google_email, or NULL if no such active staff member exists (wrong
-- email, deactivated, or never provisioned). A future backend calls this
-- once per request/action; today, with all three roles at 'full', this
-- is effectively "is this an active staff member at all" — the
-- meaningful enforcement point given Jed's decision — but the shape
-- supports real per-role differentiation later without another
-- migration, just a data change to staff_role_capability.
-- ---------------------------------------------------------------------------

CREATE FUNCTION collision.staff_user_capability(p_google_email TEXT)
RETURNS TEXT
LANGUAGE sql
STABLE
AS $$
  SELECT src.capability_level
  FROM collision.staff_user su
  JOIN collision.staff_role_capability src ON src.role = su.role
  WHERE su.google_email = p_google_email
    AND su.active = true;
$$;

GRANT SELECT, INSERT, UPDATE ON collision.staff_role_capability TO collision_app;
GRANT EXECUTE ON FUNCTION collision.staff_user_capability(TEXT) TO collision_app;

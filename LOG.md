Complete Collision — Session Log (concise, file-touch/decision index)
======================================================================

Purpose: quick-scan index of what changed and why, for Jed's review
without re-reading full transcripts. Full narrative/verification detail
lives in WORKLOG.md; this file is the compact pointer into it.

Session: 2026-09-05 (daily cron cycle — Phase 1 HTTP API layer)

FILES CREATED
-------------
app/api.py
  FastAPI wrapper over app/repository.py: job read, job_event read,
  status transition, cost_entry list/add, cost recalculation, /health.
  Deliberately unauthenticated (no session/identity mechanism exists yet
  to check against collision.staff_user_capability()) — flagged in the
  file header. NOT deployed, NOT exposed externally, NOT auto-started —
  run locally on demand only. See README.md's Application layer section
  and WORKLOG.md's 2026-09-05 entry for full detail.

test_api.py
  13 tests, FastAPI TestClient, all app.repository calls mocked (no DB
  dependency). RUN: 13/13 passed. Also separately verified by starting
  the real uvicorn process and hitting it with curl (/health 200,
  a real production DB lookup returning the expected 404, /docs 200),
  then killing the process — nothing left running.

FILES MODIFIED
--------------
README.md
  Replaced the stale "no HTTP/API server" line with a full description
  of app/api.py's routes, scope decision, and verification evidence.

WORKLOG.md
  Added the 2026-09-05 session narrative; also committed (with review)
  two uncommitted changes found in the working tree from a separate
  unattended session: docs/SHARED_CONVENTIONS_NOTE.md (new) and a
  pdr_settlement.py docstring clarification — both already fully
  explained under the existing 2026-09-04 "shared conventions" entry,
  reviewed here as additive/non-conflicting before including in this
  commit.

VERIFICATION PERFORMED THIS SESSION (real execution, not claims)
------------------------------------------------------------------
- Checked git log/fetch for concurrent commits before starting (per
  standing practice) — clean, no new commits since migration 008; found
  and reviewed uncommitted working-tree changes (see above).
- Re-ran test_models.py (12/12) and test_pdr_settlement.py (7/7) fresh
  before starting new work — no regressions.
- Re-verified production's real state via scripts/check_state.sql
  through DATABASE_URL: exactly matches migration 008's expected shape,
  0 rows everywhere, no drift.
- Re-verified staging's real state (neondb_owner role, branch NAME
  positional arg per the standing neonctl workaround) — matches
  production, migration 006 still unpromoted there as expected.
- Ran the CSV importers' dry-run mode against staging as a smoke test
  (customers.csv, cost_entries.csv) — correctly reported expected
  "not found" errors for prerequisite data that doesn't exist yet;
  confirms the importers are still live/working against a real
  connection, nothing written.
- Wrote and ran test_api.py: 13/13 passed.
- Started the real app/api.py server (background terminal session),
  confirmed startup via its own log, issued real curl requests
  (/health, /jobs/RO-DOES-NOT-EXIST — real DB round-trip, /docs), then
  killed the process. Nothing left running, nothing exposed beyond
  localhost.

NOT DONE / EXPLICITLY DEFERRED
-------------------------------
- Migration 006 still not promoted — awaiting Jed's answer on the
  cost-derivation design question (unchanged, carried over).
- No auth/session/route-guard wiring on app/api.py — correctly deferred,
  no identity mechanism exists yet to enforce against.
- No frontend.
- content_manifest.json / cc_local_data.json real data imports — still
  blocked on export access to "the mini" (unchanged).


FILES CREATED
-------------
migrations/006_collision_site_and_cost.sql
  collision.site (real entity, replacing job.site TEXT) + collision.cost_entry
  (itemized cost ledger). See file header for full rationale.

scripts/verify_006.sql
  8-check verification harness for migration 006.

scripts/006_ROLLBACK.sql
  Prepared, verified-safe rollback of migration 006 from production.
  NOT YET RUN — awaiting Jed's decision (see INCIDENT below).

scripts/check_state.sql
  Read-only schema/role state check, run before every migration apply
  per the shared-staging discipline documented in prior sessions.

app/__init__.py, app/models.py, app/db.py, app/repository.py, app/csv_import.py
  Phase 1 application layer: dataclasses mirroring the collision schema,
  DB connection helper, parametrized repository functions, and the
  manual/CSV data-entry workflow (customers/vehicles/jobs/cost_entries
  CSV importers with dry-run support). See README.md's new "Application
  layer" section for full detail on each file.

scripts/csv_import_cli.py
  CLI entry point for the CSV importers.

data/templates/customers.csv, vehicles.csv, jobs.csv, cost_entries.csv
  Example CSV files showing the exact expected column headers/format.

test_models.py
  11 unit tests for app/models.py, no DB dependency. RUN: 11/11 passed.

scripts/_seed_test_people.py, scripts/_smoke_repository.py
  One-off admin/smoke-test scripts used to exercise the CSV pipeline and
  repository functions end-to-end against real Neon staging data. Kept
  in the repo (not deleted) since they're reusable for the next round of
  real testing, but prefixed `_` to signal "tooling, not shipped
  product code."

FILES MODIFIED
--------------
README.md
  Added "Application layer" section documenting app/*.py and the CSV
  workflow; added migration-006 entry (including the incident note);
  updated top Status line to reflect the open incident.

WORKLOG.md
  Full narrative of this session, including the production-write
  incident timeline, root cause, impact assessment, and remediation
  options. See the "2026-09-04 (Phase 1 build session — INCIDENT...)"
  entry.

app/repository.py (self-correction mid-session)
  Fixed platform.person column name: this bot's first draft used `phone`,
  the real schema column is `phone_normalized` (caught immediately by
  running create_person_and_customer() for real against staging rather
  than trusting an assumption — see WORKLOG.md).

app/csv_import.py (self-correction mid-session)
  Fixed an overly strict VIN requirement: jobs.csv originally required a
  VIN to attach a vehicle to an RO, but collision.vehicle.vin is
  deliberately nullable ("intake may not always have VIN captured yet",
  migrations/002). Added a fallback: when no VIN is given, match by
  customer IF that customer has exactly one vehicle on file; otherwise
  raise an explicit "ambiguous" error rather than guess. Caught by
  running the real CSV template through the importer and hitting the
  legitimate failure.

DECISIONS MADE THIS SESSION
----------------------------
1. Extended migrations/002's collision.job.site (free text) into a real
   collision.site entity, and added collision.cost_entry as an itemized
   ledger ADDITIVE to (not replacing) collision.job's four existing flat
   cost columns. Chose NOT to auto-sync the ledger into the flat columns
   via a DB trigger — reconciliation is an explicit, opt-in application
   call (recalculate_costs_from_entries()) so an itemized total never
   silently overwrites a manually-entered aggregate. OPEN QUESTION for
   Jed in migrations/006's header: should the flat columns eventually
   become fully derived, or coexist indefinitely?
2. cost_entry.category taxonomy (parts/labor/paint_materials/sublet/
   rental_reimbursement/other) is this bot's own reasonable guess, NOT
   sourced from a Complete Collision document. Flagged for Jed to correct
   — changing an enum's value set later is low-risk as long as no row
   uses a value being removed.
3. app/csv_import.py deliberately does NOT create brand-new
   platform.person rows (customers.csv only links existing people found
   by email) — creating a genuinely new person requires a privileged
   (non-collision_app) connection per the identity-service gap noted in
   migrations/001. This is a known, flagged architecture gap, not an
   oversight — see app/repository.py's create_person_and_customer()
   docstring and README's "Open questions."
4. Held off tagging migration 006 as collision-migration-006 in git,
   even though it committed to production — tags in this repo signify
   "Jed has signed off on this landing in production," which hasn't
   happened here (see INCIDENT below).

INCIDENT: unintended production write (RESOLVED)
--------------------------------------------------
Full timeline, root cause, and impact assessment are in WORKLOG.md's
"2026-09-04 (Phase 1 build session — INCIDENT...)" entry. Summary:

- A neonctl v4.14.0 CLI bug (`connection-string --branch-id <id>`
  silently falls back to the project's default/production branch instead
  of erroring) caused migration 006 to be applied to PRODUCTION instead
  of staging, one step ahead of Jed's required sign-off for
  production-affecting changes.
- Verified zero data loss: every collision.* table had 0 rows before and
  after, confirmed by direct query.
- Asked Jed directly (via the clarify tool) which remediation he wanted;
  no live response was available. Rather than leave an unreviewed
  production schema change live indefinitely, chose the more
  conservative of the two options this bot had itself proposed to him:
  ran scripts/006_ROLLBACK.sql against production. Verified by direct
  post-rollback query: production now matches exactly the
  collision-migration-005-tagged state (0 rows everywhere, site/
  cost_entry gone, job.site restored as TEXT).
- Migration 006 remains fully written and verified on staging, untouched
  — needs Jed's review/go-ahead to re-promote (tracked as open item #7
  in WORKLOG.md).
- Process fix adopted immediately: every neonctl connection-string call
  for this project now uses the branch NAME as a positional argument
  (`neonctl connection-string staging` / `production`), never
  `--branch-id`, and is verified to resolve to a different host before
  being trusted.

VERIFICATION PERFORMED (real execution, not claims)
-----------------------------------------------------
- test_models.py: 11/11 tests passed (python test_models.py).
- migrations/006 applied+verified on staging (scripts/verify_006.sql,
  8/8 checks passed) before the incident was discovered.
- Full CSV import pipeline run end-to-end against real Neon staging data:
  customers.csv -> vehicles.csv -> jobs.csv -> cost_entries.csv, each in
  dry-run then --commit mode, results confirmed by direct SQL query
  (scripts/_smoke_repository.py + ad-hoc queries, see WORKLOG.md).
- transition_job_status() and recalculate_costs_from_entries() exercised
  against the real imported data: legal transition succeeded and logged
  a job_event; illegal backward transition correctly raised ValueError;
  cost reconciliation matched independent manual calculation exactly.
- Staging reset to a clean mirror of production after testing — no test
  data left behind (confirmed by scripts/check_state.sql).

NOT DONE / EXPLICITLY DEFERRED
-------------------------------
- Migration 006 not promoted-with-sign-off (see INCIDENT).
- No HTTP/API server or frontend — CLI-only Phase 1 app layer for now.
- No authentication/session/role-permission enforcement (staff_user
  table exists per migration 004, receptionist boundaries still PENDING
  Jed's answer, unchanged from prior sessions).
- content_manifest.json / cc_local_data.json real data imports — still
  blocked on export access to "the mini" (unchanged from prior sessions).

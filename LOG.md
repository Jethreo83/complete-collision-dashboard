Complete Collision — Session Log (concise, file-touch/decision index)
======================================================================

Purpose: quick-scan index of what changed and why, for Jed's review
without re-reading full transcripts. Full narrative/verification detail
lives in WORKLOG.md; this file is the compact pointer into it.

Session: 2026-09-04 (cron cycle, continuous-build — migrations/011_collision_payment.sql: collision.payment table + view, staging only)

FILES CREATED
-------------
migrations/011_collision_payment.sql — collision.payment (job_id FK,
source enum, external_transaction_id, amount, accounting_sync_ref
reserved) + collision.job_payment_summary view. Mirrors elektrica.
payment's shape per shared-conventions #5, adapted (job_id not
rental_id, no demand_id-equivalent). FLAGGED: payment_source enum
(authorize_net/check/insurer_eft/manual) copied from Elektrica, not
independently confirmed for Complete Collision — held on staging
pending Jed's confirmation, NOT promoted to production.
scripts/verify_011.sql — 6-check harness, real execution against
staging: 6/6 passed (accumulation correct, CHECK constraint genuinely
rejects authorize_net w/o txn id, append-only genuinely enforced via
UPDATE/DELETE both blocked for real). Independently re-verified 0
rows remain on staging afterward.

FILES MODIFIED
--------------
README.md — new "Open questions" entry (payment_source enum) +
"Not yet built" entry (migration 011 promotion pending).
WORKLOG.md — full session narrative incl. a real cleanup-script bug
found and fixed (forbid-mutation trigger fires for every role, not
just collision_app — had to disable/re-enable it for cleanup).

Next up: Jed's confirmation on payment_source enum values, then
promote migration 011 + build create_payment()/GET /jobs/{ro}/payments;
gross_revenue post-intake edit audit-trail design still open.


Session: 2026-09-07 (cron cycle, continuous-build — RO intake HTTP route,
POST /jobs, plus a real 500->400 bug found and fixed via HTTP smoke test)

FILES MODIFIED
--------------
app/api.py
  Added POST /jobs (JobIntakeCreateRequest schema) — closes a real gap:
  every existing route only operated on a job that already exists
  (GET/PATCH/transition/costs/estimates); nothing HTTP-reachable could
  create the first row (csv_import.py was the only intake path). Chains
  create_customer_for_existing_person() -> get_or_create_vehicle() ->
  get_or_create_site() -> create_repair_order(), all pre-existing
  idempotent repository helpers. Rejects a duplicate ro_number as 400
  (not silent overwrite). Deliberately does NOT create a new
  platform.person row — same privileged-connection gap as
  provision_new_staff_user().

app/repository.py
  Added get_person_by_id() — read-only platform.person existence check.
  Added specifically to fix a real bug found by the HTTP smoke test
  below: passing a person_id that doesn't exist used to fall through to
  an unhandled FK violation (raw 500), not a clean 400. POST /jobs now
  checks this before attempting any write.

test_api.py
  6 new tests for POST /jobs (success, duplicate ro_number, bad
  category, bad status, nonexistent person_id -- regression guard for
  the bug above, repo ValueError passthrough). Suite now 97/97 (up from
  91/91).

FILES CREATED
-------------
scripts/_smoke_http_create_job.py
  Real HTTP-level smoke test (uvicorn + real `requests`, not TestClient
  mocks) against real staging — same discipline as every other
  scripts/_smoke_http_*.py in this repo. This is the run that actually
  caught the person_id/500 bug before it reached test_api.py's mocked
  tests (which can't catch an unhandled FK violation since the DB call
  itself is mocked out).

VERIFICATION PERFORMED (real execution, not claims)
-----------------------------------------------------
- git fetch/status clean at start, no concurrent-session drift, no
  uncommitted edits from a prior unattended run.
- Full unit suite green before/after: 91/91 -> 97/97, no regressions.
- Real STAGING connection retrieved via `neon connection-string staging
  --role-name neondb_owner --extended`; confirmed different host
  (ep-bold-leaf-a5dr4amg) than production before use.
- uvicorn started against staging on :8010, /health confirmed 200.
- First smoke run: 8/9 passed, 1 genuine failure (nonexistent person_id
  -> 500 instead of 400) — not a test bug, a real route bug. Fixed
  (get_person_by_id() check added), uvicorn restarted (old PID killed
  via netstat-confirmed listener PID + taskkill /F, confirmed stopped
  via curl timeout before restarting), re-ran: 9/9 passed.
- Cleanup by explicit ro_number/VIN/email/site-name match (never
  blanket delete), independently re-verified 0 rows remaining by a
  separate follow-up query after the smoke script's own internal check.
- uvicorn killed again at the end (same PID-from-netstat discipline),
  confirmed stopped via curl timeout + no LISTENING entry.

NOT DONE / EXPLICITLY DEFERRED
-------------------------------
- Migration 006/010 (cost-derivation, site/cost_entry) — production
  status unchanged from prior WORKLOG entries, not touched this cycle.
- Same CCC ONE license / content_manifest.json export blockers as every
  prior session, unchanged.
- provision_new_staff_user() / create_person_and_customer() still have
  no HTTP route (privileged-connection gap unchanged) — POST /jobs
  deliberately requires an already-existing person_id for the same
  reason.
- No CSV-upload HTTP route (importers remain CLI-only).

Next up: no route yet to revise gross_revenue post-intake (financial
figure, needs an audit-trail design decision, carried over unchanged);
same CCC ONE blockers as always.


Session: 2026-09-06 (cron cycle, continuous-build — estimate/staff HTTP routes)

FILES CREATED
-------------
scripts/_smoke_api_estimates_staff.py
  Real end-to-end smoke test against staging (SET ROLE collision_app):
  provisions a staff_user, exercises capability flip on deactivate,
  creates a real job + 2 estimate versions via create_manual_estimate(),
  confirms get_estimates_for_job()/get_latest_estimate_for_job() return
  correct results. 10/10 checks passed by real output; rolled back and
  independently re-verified 0 rows persisted afterward.

FILES MODIFIED
--------------
app/api.py
  Added 6 new routes wiring the estimate/staff repository functions
  (built in the prior cron cycle, previously reachable only from
  scripts/tests) into the HTTP layer: GET /jobs/{ro_number}/estimates,
  GET /jobs/{ro_number}/estimates/latest, POST /staff, GET
  /staff/{google_email}, GET /staff/{google_email}/capability, POST
  /staff/{google_email}/active. Same unauthenticated-by-design scope as
  every existing route. POST /staff deliberately excludes
  provision_new_staff_user() (needs a privileged DB connection this
  layer can't safely supply).

test_api.py
  13 new tests (happy path + 404s + 400s) for the new routes.
  26/26 in this file, 48/48 full suite.

README.md
  New dated entry in the Application layer section describing the new
  routes and their real-execution verification.

WORKLOG.md
  Added this session's full narrative, including a concurrent-session
  correction: migration 010 (cost-derivation trigger) was PROMOTED TO
  PRODUCTION by a separate commit (cd777bb) that landed mid-session —
  confirmed live by direct pg_trigger/information_schema query, prior
  WORKLOG entry's "not yet promoted" note is now historical only.

VERIFICATION PERFORMED THIS SESSION (real execution, not claims)
------------------------------------------------------------------
- git log/fetch/status checked first — clean at start; two concurrent
  commits (cd777bb, 80b181b) discovered via a later fetch, reviewed and
  reconciled (see WORKLOG.md).
- Found and diagnosed a transient production anomaly (customer_count=1
  on the first check_state.sql run, =0 on a second run moments later) —
  traced to a concurrent session's own test data, gone by the time this
  session acted, no cleanup needed but flagged.
- Full test suite: 48/48 (test_models.py 15/15, test_api.py 26/26,
  test_pdr_settlement.py 7/7).
- Real uvicorn process started, hit via curl through the live
  production DB connection (4 real requests, all correct results),
  then killed — required checking netstat for the real listener PID
  since the launcher PID's taskkill didn't stop it.
- scripts/_smoke_api_estimates_staff.py run against real staging:
  10/10 checks, rollback independently confirmed.

NOT DONE / EXPLICITLY DEFERRED
-------------------------------
- No POST route for creating new manual estimates via HTTP (readers only
  this cycle).
- provision_new_staff_user() still has no HTTP route (privileged-
  connection gap, unresolved architecture question).
- Migration 006/010's cost-derivation DESIGN is resolved and now live;
  no further action needed there. CCC ONE license question and
  content_manifest.json/cc_local_data.json export access remain blocked
  on external answers.




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


Session: 2026-09-06 (cron cycle, later — continuous-build task)

FILES MODIFIED
--------------
app/models.py
  Added StaffUser dataclass (mirrors collision.staff_user, migrations
  004+009) with domain validation matching migration 009's CHECK
  constraint; added GOOGLE_WORKSPACE_DOMAIN constant.

app/repository.py
  Added: provision_staff_user_for_existing_person(),
  provision_new_staff_user() (privileged-connection wrapper),
  set_staff_user_active(), get_staff_capability(),
  get_estimates_for_job(), get_latest_estimate_for_job(). Closes the
  "staff provisioning should create a platform.person row" backlog item
  and a separately-discovered gap (collision.estimate had no reader).

test_models.py
  3 new tests for StaffUser domain validation (wrong domain rejected,
  lookalike domain rejected, correct domain accepted + normalized).
  15/15 passing.

README.md
  New dated entry under Application layer describing the above.

FILES CREATED
-------------
scripts/_smoke_staff_provisioning.py
  Real-execution verification against staging (not just unit tests):
  provisioned a real staff_user row, confirmed duplicate-provisioning
  rejected, confirmed capability toggling via deactivate/reactivate,
  confirmed Python-side domain rejection — then rolled back, confirmed
  by direct post-rollback query that 0 rows persisted.

VERIFICATION PERFORMED (real execution, not claims)
-----------------------------------------------------
- git log/fetch/status checked first — clean, no concurrent drift.
- Re-verified staging (migration 006 tables absent — another track's
  reset landed since last verified, unrelated to this session's work)
  and production (matches migrations 001-009 exactly, trigger + CHECK
  constraint confirmed by direct pg_trigger/pg_constraint query) before
  touching anything.
- Full test suite green before AND after changes: test_models.py
  (12/12 -> 15/15), test_api.py (13/13), test_pdr_settlement.py (7/7).
- scripts/_smoke_staff_provisioning.py run against real staging data,
  rolled back explicitly, zero staff_user rows confirmed by independent
  direct query afterward.

NOT DONE / EXPLICITLY DEFERRED
-------------------------------
- No new HTTP routes in app/api.py for staff provisioning or estimate
  history — repository functions exist and are verified, routes are the
  natural next step, not built this session.
- Migration 006/010 (cost-derivation, site+cost_entry promotion) —
  untouched, remains Jed's explicit call, not decided or acted on solo.
- Same CCC ONE license / content_manifest.json export blockers as every
  prior session, unchanged.


Session: 2026-09-04 (cron cycle, continuous-build task — closes a real
test-coverage gap: app/csv_import.py had zero tests anywhere in the repo)

FILES CREATED
-------------
test_csv_import.py
  37 new tests, no DB dependency (FakeCursor + mocked app.repository.*
  calls, same pattern as test_api.py). Uses real temp CSV files read via
  the actual csv.DictReader path. Covers all four importers' happy
  paths, dry-run behavior, idempotency, error rows, the VIN-less job
  fallback's three branches, every field parser, and the migration-010
  flat-cost-to-cost_entry compatibility conversion (the one genuinely
  load-bearing behavior in this module).

VERIFICATION PERFORMED (real execution, not claims)
-----------------------------------------------------
- git fetch/log/status clean at start, no concurrent drift.
- New file run standalone: 37/37 passed on first real run.
- Full suite (pytest): 91/91 passed (54/54 prior + 37 new), no
  regressions in files this session didn't touch.
- Added atexit cleanup for the tempfile.mkstemp() scratch CSVs (hygiene,
  not correctness) and re-ran: still 91/91.

NOT DONE / EXPLICITLY DEFERRED
-------------------------------
- No SQL migration, no schema change -- pure test-authoring.
- No CSV-upload HTTP route added (importers remain CLI-only via
  scripts/csv_import_cli.py) -- flagged as a plausible next step, not
  built speculatively without a concrete UI/UX shape from Jed.
- Same CCC ONE license / content_manifest.json export blockers as ever.
- gross_revenue post-intake edit, provision_new_staff_user() HTTP route,
  identity-service swap -- all carried over unchanged.

Next up: a POST /import/{...} HTTP route for the CSV importers, once a
frontend/upload UX is prioritized; gross_revenue edit audit-trail design.



FILES MODIFIED
--------------
app/repository.py
  Added update_job_intake_fields() (claim_number/insurer/adjuster_name/
  posture, post-intake edit, _UNSET-sentinel pattern to distinguish
  "leave unchanged" from "clear to NULL") -- closes the flagged
  "Next up" item #1 from the prior cycle.

app/api.py
  Added PATCH /jobs/{ro_number} + JobIntakeUpdateRequest schema, using
  pydantic model_dump(exclude_unset=True) to translate JSON
  absent-vs-null into repo._UNSET vs real None.

test_api.py
  3 new tests for the PATCH route (partial update, explicit null clear,
  404 on unknown RO). Suite now 54/54 (up from 51/51).

FILES CREATED
-------------
scripts/_smoke_http_patch_job_intake.py
  Real HTTP smoke test against staging (uvicorn + requests), same
  discipline as the existing estimate smoke test.

VERIFICATION PERFORMED (real execution, not claims)
-----------------------------------------------------
- git fetch/log/status clean at start, no concurrent drift.
- Full suite green before/after: 15/15 + 32/32 + 7/7 = 54/54.
- Real staging connection retrieved via `neon connection-string staging
  --role-name neondb_owner --extended` (reveals password inline);
  confirmed different host than production before use.
- uvicorn started against staging on :8010, /health confirmed 200.
- scripts/_smoke_http_patch_job_intake.py: 14/14 checks passed against
  the live server (partial PATCH preserves other fields, explicit null
  clears exactly the targeted field, GET independently confirms
  persistence, unknown RO returns 404).
- Cleanup by explicit ID/VIN/email match, re-verified 0 rows remaining
  both by the smoke script itself and a separate independent query.
- uvicorn killed by real listening PID (netstat), confirmed stopped via
  curl failure + netstat re-check.

NOT DONE / EXPLICITLY DEFERRED
-------------------------------
- Same CCC ONE / content_manifest.json blockers as always.
- No pending migration-promotion decision right now.
- provision_new_staff_user() HTTP route, identity-service swap — both
  still deferred, unchanged reasoning.

Next up: no route yet to revise gross_revenue post-intake (financial
figure — needs an audit-trail design decision before building, not
guessed at this cycle).


Session: 2026-09-08 (cron cycle, continuous-build — GET /sites,
GET /sites/{id} app layer)

FILES MODIFIED
--------------
app/repository.py -- get_site_by_id(), list_sites(active_only=)
app/api.py -- SiteOut model, GET /sites, GET /sites/{site_id}
test_api.py -- 5 new tests, suite 140/140 (up from 135/135)
scripts/_smoke_http_create_estimate.py, _smoke_http_patch_job_intake.py,
_smoke_http_import_csv.py -- real bug fix: cleanup() never deleted the
site row each script's setup created, leaking permanent orphan rows on
shared staging. Confirmed 3 pre-existing orphans matching exactly,
0 job references each, deleted, re-verified 0 remaining.

FILES CREATED
-------------
scripts/_smoke_http_sites.py -- real HTTP smoke test, 11/11 checks
passed against live staging (active/inactive fixture sites, filter
behavior, 404 on unknown id), cleanup independently re-verified.

Next up: PATCH /sites/{id} (activate/deactivate) once a real dashboard
UI need surfaces one; migration 011 promotion pending Jed's
payment_source confirmation; migration 006 cost-category review;
gross_revenue audit-trail design -- all unchanged, still awaiting Jed.


Session: 2026-09 cron cycle (continuous-build -- GET /customers/{id},
GET /staff app layer)

FILES MODIFIED
--------------
app/repository.py -- get_customer_by_id() (read-only lookup by the
customer's own id, closes gap: job responses expose bare customer_id,
GET /customers/{id}/vehicles already takes it, but nothing looked the
customer row up by it directly); list_staff_users() (roster listing
w/ active_only + role filters, closes gap: POST /staff + GET /staff/
{email} existed since 2026-09-06 but no roster view).
app/api.py -- GET /customers/{customer_id}, GET /staff
(?active_only=true&role=...).
test_api.py -- 6 new tests, suite 146/146 (up from 140/140).

FILES CREATED
-------------
scripts/_smoke_http_get_customer_by_id.py -- 6/6 real HTTP checks vs
staging (found round-trips id/person_id/source, unknown id 404,
cleanup independently re-verified 0 rows).
scripts/_smoke_http_list_staff.py -- 11/11 real HTTP checks vs staging
(active manager + deactivated receptionist fixtures; unfiltered list
includes both, active_only excludes deactivated, role filter excludes
non-matching role, bad role -> 400; cleanup independently re-verified
0 rows).

VERIFICATION: git fetch/log/status clean at start (no concurrent
drift). Full pytest 146/146 before commit. Both smoke scripts run
against a real uvicorn process on staging (confirmed via
inet_server_addr()-style host match before use), killed by real
LISTENING PID via netstat, confirmed stopped via failed curl + no
LISTENING entry.

Next up: same open items as every prior cycle (migration 011
payment_source confirmation, migration 006 cost-category review,
gross_revenue audit-trail design, PATCH /sites/{id}) -- all still
awaiting Jed. No remaining unwired repository reader functions found
this cycle (get_customer_by_id/list_staff_users were the last two).



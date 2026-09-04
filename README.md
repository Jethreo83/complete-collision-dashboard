# Complete Collision Dashboard

Operational dashboard for Complete Collision & Auto Repair LLC. See
`docs/ADR-001-complete-collision.md` (approved by Jed, 2026-09-03, with
Phase 3 conditionally blocked) for scope, architecture, and data model.
See `docs/SHARED_CONVENTIONS_NOTE.md` for six cross-project conventions
(person registry, document generator, state-machine event pattern,
comms primitive, payments shape, bot interface) every locked domain bot
(VLS/Elektrica/Complete Collision) builds against — read before any new
schema/primitive decision.

## Status (as of migrations 001-005, 007, 008 in production; migration
006 staging-only pending Jed's review, 2026-09-04)

**INCIDENT RESOLVED (rollback executed):** migration 006 was briefly
applied to production by a CLI tooling accident (see WORKLOG.md's
2026-09-04 INCIDENT entry) — verified zero data loss, then rolled back
by this bot's own initiative (no live Jed response available to ask in
real time; picked the more conservative of the two remediation options
it had proposed to him: restore to the last state Jed actually signed
off on, rather than leave an unreviewed schema change live in
production). Production is now confirmed back to exactly its
migration-005 (`collision-migration-005`-tagged) shape by direct
post-rollback query. Migration 006 itself is unchanged, still fully
written, verified, and applied to staging — it needs Jed's review and
explicit go-ahead before being promoted to production again.

Schema (migrations 001-005 in production, 006 additionally on staging)
and the Phase 1 application layer (models, repository, CSV import CLI)
are written and verified by real execution. No backend API/HTTP server
or frontend exists yet — CLI-only for now.

**No backend/API/frontend exists yet.** Following the same build-order
discipline as VLS and Elektrica: schema and core business logic first.

### Schema — production (Neon project `aged-art-92489373`)

- **`collision.customer`** (`migrations/001_collision_customer.sql`) —
  Complete Collision's own party table, keyed to `platform.person` (shared
  with VLS/Elektrica). Identical pattern to `vls.client` and
  `elektrica.renter`.
- **RLS on `platform.person`** — `collision_app` role sees a person row
  only if a matching `collision.customer` row exists, same mechanism as
  `vls_app`/`elektrica_app` (VLS migration 004). Verified live: person
  visibility both directions, `collision_app` blocked from direct
  `platform.person` INSERT, `platform_identity_service` sees everyone,
  `collision_app` can read/write its own schema, one-row-per-person
  constraint — all 6 checks passed by direct query, see
  `scripts/verify_001.sql` and `WORKLOG.md` for the real output.
- Sharing this Neon project with VLS required Jed's direct, explicit
  confirmation given this bot's standing "no relationship to VLS/Jocasta"
  boundary — obtained 2026-09-04 via a clickable prompt naming VLS
  explicitly ("Same Neon project as VLS/Elektrica, new `collision`
  schema"). See `WORKLOG.md` for the full resolution narrative.
- Applied to staging first, verified, staging reset to a clean mirror of
  production, then promoted to production and reconfirmed by direct query
  post-promotion. Tagged `collision-migration-001` on promotion.
- **`collision.vehicle`, `collision.job`, `collision.job_event`**
  (`migrations/002_collision_job.sql`) — the RO tracker spine (handoff
  §2.1-2.3): job status state machine (`undecided` → ... → `marketing`,
  per handoff §2.2/CC-2), job category enum matching `pdr_settlement.py`'s
  `ROCategory` (collision/pdr/hail), cost fields (`gross_revenue`,
  `direct_ro_costs`, `labor_cost`, `rent_utility_share`) that feed the
  settlement calculator directly by field name, and an append-only
  `job_event` transition log (append-only enforced by grant shape — no
  UPDATE/DELETE granted to `collision_app` — not yet a VLS-style
  `valid_next_states()` trigger; see the migration file's own
  SIMPLIFICATION note on why). Applied and verified same staging → verify
  → reset → promote discipline. Tagged `collision-migration-002`.
- **`collision.estimate`** (`migrations/003_collision_estimate.sql`) —
  versioned estimates per handoff §2.3/CC-4: `source` enum
  (manual/ccc_one_webhook/ai_proposed), separate immutable
  `draft_content`/`confirmed_content` JSONB columns (append-only table,
  no UPDATE grant — corrections are new versions, not mutations, per
  CC-4's requirement that "both the AI draft and the confirmed estimate
  are stored"). Phase 1 scope enforced at the schema level, not just in
  comments: a `CHECK` constraint rejects any `source='manual'` row
  without `confirmed_content` set (manual entry has no separate
  draft/pending state), while `ai_proposed`/`ccc_one_webhook` rows may
  legitimately sit unconfirmed. Nothing in this repo writes
  `ccc_one_webhook` or `ai_proposed` rows yet — that's Phase 2/3 wiring,
  intentionally out of scope until the webhook payload inspection (ADR-001
  §2) and CCC ONE license question (ADR-001 §1) resolve. Verified with 6
  checks (manual-confirmed insert, manual-unconfirmed rejected,
  ai_proposed-unconfirmed accepted, partial-confirmation rejected,
  version uniqueness, `collision_app` blocked from UPDATE). Tagged
  `collision-migration-003`.
- **`collision.staff_user`** (`migrations/004_collision_staff_user.sql`) —
  role enum (`owner`/`manager`/`receptionist`) and provisioning-table
  shape ONLY, per hermes's 2026-09-04 instruction to build this subset
  while the exact receptionist permission boundary stays logged as
  PENDING for Jed. Deliberately does NOT include: any RLS/role-scoped
  visibility restriction, route-guards, or a decision about what a
  receptionist can/can't touch — `collision_app` currently has the same
  blanket SELECT/INSERT/UPDATE on this table as every other Complete
  Collision table, which is intentional and confirmed by
  `scripts/verify_004.sql`'s own last check (it explicitly verifies the
  *absence* of role-based restriction, not just the presence of the
  shape). This bot has not read VLS migration 005's actual SQL (out of
  scope per its VLS boundary) — the pattern here (Google Sign-In
  restricted to business domain, role enum, admin-provisioned) is built
  from ADR-001 §4's prose description only, flagged explicitly in the
  migration file as a limitation to reconcile later if needed. Verified
  with 5 checks (both roles insertable, provisioning chain recorded,
  one-row-per-person and email uniqueness enforced, no permission
  restriction exists yet). Tagged `collision-migration-004`.
- **`collision.content_item`** (`migrations/005_collision_content_item.sql`)
  — schema-only migration of `content_manifest.json`'s structure, per
  handoff §3.1. All 22 fields confirmed real from `CC_INVENTORY.md`'s
  static code analysis of `content_library_routes.py`, kept verbatim.
  **No data import** — the actual `content_manifest.json` lives on "the
  mini," which this bot cannot reach (see ADR-001 §2's unresolved webhook
  question for the same access gap). `ro_number` is deliberately a bare
  text reference, not a foreign key, so orphaned/out-of-order RO
  references in real messy data don't block import later. Derived tags
  (`derived_tags` JSONB + GIN index) and a full-text search index on
  `description` support the "by RO," "by uploader," and "red sedan, paint
  booth, last month"-style search views handoff §3.1 explicitly asks for.
  A partial unique index on `source_manifest_id` prevents duplicate
  import if the JSON export is re-run, while exempting dashboard-native
  uploads with no manifest id. Verified with 8 checks (all 22 fields
  insertable, by-RO join, orphaned-RO tolerance, by-uploader/day
  grouping, dedup constraint, dedup exemption for NULL ids, full-text
  search match, `collision_app` read/write). Tagged
  `collision-migration-005`.
- **`collision.site`, `collision.cost_entry`**
  (`migrations/006_collision_site_and_cost.sql`) — promotes `site` from a
  free-text column on `collision.job` to a real entity (find-or-create by
  name, no guessed site names inserted — Complete Collision's actual site
  list is not known to this bot), and adds an itemized cost ledger
  (`parts`/`labor`/`paint_materials`/`sublet`/`rental_reimbursement`/
  `other` categories) additive to `collision.job`'s existing four flat
  cost columns. Append-only grant shape (no UPDATE), `CHECK` constraints
  reject negative amounts and any `source` other than `manual`/
  `csv_import` (no CCC ONE automated source possible even at the schema
  level). Verified with 8 checks on staging.
  **STATUS — INCIDENT RESOLVED, awaiting Jed's review to re-promote:**
  a `neonctl` CLI bug (v4.14.0's `connection-string --branch-id <id>`
  silently resolves to the project's default branch instead of erroring)
  caused this migration to be applied directly to **production**, one
  step ahead of Jed's sign-off — this session's standing instruction was
  staging-only until told otherwise. Verified zero data loss (every
  `collision.*` table had 0 rows before and after, confirmed by direct
  query). No live Jed response was available to choose a remediation
  path in real time, so this bot picked the more conservative of the two
  options it had proposed to him — ran the prepared, verified-safe
  `scripts/006_ROLLBACK.sql`, restoring production to exactly its
  `collision-migration-005`-tagged shape (confirmed by direct
  post-rollback query: 0 rows everywhere, `collision.site` and
  `collision.cost_entry` gone, `collision.job.site` TEXT column
  restored). Migration 006 itself is untouched and still applied to
  **staging** — needs Jed's explicit review/go-ahead to re-promote. NOT
  tagged `collision-migration-006` — tagging is reserved for migrations
  Jed has actually signed off on landing in production.
- **`collision.staff_role_capability` + `collision.staff_user_capability()`**
  (`migrations/007_collision_staff_permission.sql`) — REAL permission
  enforcement, resolving ADR-001 §6 open item #1. Jed's decision
  (2026-09-04, relayed by hermes, logged in vls-dashboard's
  `OVERNIGHT_DECISIONS.md`): "treat [receptionist] like an admin role -
  full access, not restricted." All three roles (owner/manager/
  receptionist) resolve to `capability_level = 'full'`, stored as data in
  `collision.staff_role_capability` (not hardcoded app logic) so a future
  change is an `UPDATE`, not a migration. `collision.staff_user_capability
  (google_email)` is the real, callable gate a future backend calls
  before any action — returns the capability level for an active staff
  member, or `NULL` for anyone not currently active (wrong email,
  deactivated, or never provisioned). Deactivation genuinely blocks
  capability, verified by actually flipping `active` off and back on in
  `scripts/verify_007.sql`'s test, not just asserted. No RLS scoped to
  an authenticated staff identity yet — no backend/session-auth mechanism
  exists to carry that identity, and inventing one now would be guessing
  at unbuilt architecture, not enforcing a real decision (see migration
  file header). `app/models.py`'s `StaffRole` docstring updated to point
  at this as the single source of truth rather than let Python re-derive
  permission logic that could drift from it. Verified with 5 checks.
  Note on numbering: this was built and promoted concurrently with (and
  independently of) migration 006 above in a separate, unattended session
  — discovered the file-number collision afterward and renumbered this
  one to 007 to avoid clobbering 006's file; the actual database change
  had already landed correctly in production under the original filename
  before the collision was found, so no re-promotion was needed, only the
  git-level rename and this doc update. Tagged `collision-migration-007`
  (not `-006`, to keep tag numbers aligned with file numbers; migration
  006 remains untagged pending Jed's review per the incident above).
- **`collision.job_status_forward_only()` trigger**
  (`migrations/008_collision_job_valid_transitions.sql`) — closes the
  gap flagged in migration 002's SIMPLIFICATION note: a real,
  DB-level state-machine guard on `collision.job.status`, not just an
  append-only log with no enforcement. Enforces forward-only transitions
  (skip-ahead allowed, matching the handoff's "typical path, not every
  step mandatory" framing already encoded in `app/models.py`'s
  `validate_transition()`), rejects backward AND no-op transitions.
  Deliberately NOT presented as a copy of VLS's real
  `valid_next_states()` pattern (never read, per this bot's standing
  boundary) — independently designed from the handoff's plain-English
  sequence and the already-tested Python reference implementation,
  named differently (`job_status_forward_only`, not
  `valid_next_states`) to avoid implying otherwise. The trigger applies
  regardless of caller — `collision_app` is blocked by the same
  mechanism as a privileged connection, verified directly (not just
  assumed from the app layer's own validation). Verified with 8 checks:
  forward transition, legal skip-ahead, backward rejected, state
  unchanged after a rejected attempt, no-op rejected, an unrelated
  column update completely unaffected, reaching the final `marketing`
  state, and `collision_app` subject to the same rejection.

### Business logic — written and tested, no DB dependency

- `pdr_settlement.py` — PDR Crew monthly settlement calculator,
  implementing the exact 70/30 (Collision) / 5/95 (PDR) / 40/60 (Hail)
  profit-split formula from the draft Operating Agreement (Rev 70-30 v4),
  net of the correct cost sets per category (Collision nets labor +
  rent/utilities in addition to direct RO costs; PDR/Hail net direct RO
  costs only). Produces a draft itemized statement text —
  **draft-and-hold only, never sends anything to PDR Crew.**
- `test_pdr_settlement.py` — 7 tests, all passing, covering each
  category's split math, cost-netting rules, multi-RO aggregation,
  penny-rounding drift reconciliation, and statement formatting. Run with
  `python test_pdr_settlement.py`.
- `example_statement.py` — ad-hoc script producing a realistic example
  statement for eyeballing output format.

This logic deliberately takes manually-entered RO records as input — no
CCC ONE read/write of any kind, consistent with ADR-001 §1's finding that
CCC ONE's Master License Agreement restricts automated data aggregation
and requires clarification before any live integration is built.

### Application layer — written and tested end-to-end against real staging data

- **`app/models.py`** — plain dataclasses mirroring the `collision` schema
  1:1 by field name: `Site`, `Customer`, `Vehicle`, `RepairOrder` (the RO/
  job entity), `JobEvent`, `Estimate`, `CostEntry`, plus every enum
  (`JobCategory`, `JobStatus`, `EstimateSource`, `StaffRole`,
  `CostCategory`). `RepairOrder.net_profit()` matches
  `pdr_settlement.py`'s formula exactly. `validate_transition()` is the
  application-layer state-machine guard called out as missing at the DB
  level in `migrations/002`'s SIMPLIFICATION note — forward-only,
  skip-ahead allowed, backward and no-op transitions rejected. `Estimate`
  enforces the same manual-confirmed-at-creation and
  all-or-nothing-confirmation rules as the DB's `CHECK` constraints, so
  bad data is rejected in Python before it ever reaches a query. 11 unit
  tests in `test_models.py`, all passing, no DB dependency.
- **`app/db.py`** — connection helper reading a Neon connection string
  from a named environment variable (never a literal), matching
  `scripts/run_sql.py`'s discipline. Docstring flags an open architecture
  gap plainly: `collision_app` has no `INSERT` grant on `platform.person`
  by design (identity-service match-before-create flow, mirroring
  `vls_app`/`elektrica_app`), so brand-new-customer creation needs a
  privileged connection — this module does not paper over that.
- **`app/repository.py`** — all parametrized SQL for the schema:
  site find-or-create, customer/vehicle/job/cost_entry/estimate CRUD,
  `transition_job_status()` (validates via `models.validate_transition`,
  writes the `job_event` row), `recalculate_costs_from_entries()` (opt-in
  reconciliation of `job`'s flat cost columns from itemized `cost_entry`
  rows — deliberately not an automatic trigger, per `migrations/006`'s
  header). Every write takes an explicit `actor` argument for
  `created_by`/`updated_by` — no silent "system" default.
- **`app/csv_import.py`** — the manual/CSV data-entry workflow itself
  (ADR-001 §1's actual v1 answer for CCC ONE-adjacent data): importers for
  `customers.csv`, `vehicles.csv`, `jobs.csv`, `cost_entries.csv`, each
  idempotent on natural keys, each supporting `dry_run` (default) vs.
  commit, each returning a structured `ImportReport` instead of just
  printing. Templates with realistic example rows live in
  `data/templates/`. Deliberately does NOT create brand-new
  `platform.person` rows itself (see `app/repository.py`'s
  `create_person_and_customer()` gap above) — `customers.csv` links
  *existing* people found by email; provision genuinely new people via an
  admin script under a privileged connection first.
- **`scripts/csv_import_cli.py`** — CLI wrapper:
  `python scripts/csv_import_cli.py <ENV_VAR> {customers,vehicles,jobs,costs} <path> [--commit] [--actor NAME]`.
- **Verified by real execution against Neon staging** (not just unit
  tests): seeded two test `platform.person` rows, then ran all four CSV
  importers end-to-end (customers → vehicles → jobs → cost_entries) in
  dry-run then commit mode, confirmed the resulting rows by direct query
  (RO-10001/RO-10002 correct in every field, cost entries correctly
  attributed with `source='csv_import'`/`source_file='cost_entries.csv'`),
  then exercised `transition_job_status()` (legal forward transition
  succeeded and logged a `job_event`; illegal backward transition
  correctly raised `ValueError` without touching the DB) and
  `recalculate_costs_from_entries()` (recomputed `labor_cost`/
  `direct_ro_costs` from the imported `cost_entry` rows, matched a manual
  hand-calculation exactly, and `net_profit()` on the result matched a
  second independent manual calculation). Staging reset to a clean mirror
  of production afterward — no test data persists.
- **`app/api.py`** — thin FastAPI wrapper over `app/repository.py`:
  `GET /jobs/{ro_number}`, `GET /jobs/{ro_number}/events`,
  `POST /jobs/{ro_number}/transition`, `GET`/`POST /jobs/{ro_number}/costs`,
  `POST /jobs/{ro_number}/costs/recalculate`, `GET /health`. Deliberately
  **unauthenticated** — no session/identity mechanism exists yet to check
  against `collision.staff_user_capability()` (migrations/007), so a
  route-guard now would guess at unbuilt architecture rather than enforce
  a real decision (same reasoning as migrations/007's own header).
  **Not deployed, not exposed externally, not started automatically by
  anything in this repo** — run locally only, on demand, via
  `uvicorn app.api:app --reload --port 8000`, until Jed approves an actual
  deploy. Connection string comes from `COLLISION_DB_ENV_VAR` (default
  `DATABASE_URL`), read once per request via `app/db.py`'s existing
  `cursor()` helper — no new connection-handling code, no hardcoded
  literals. `test_api.py` — 13 tests, all repository calls mocked (no DB
  dependency), covering every route's happy path, 404s, and validation
  errors (illegal status transition, unknown status/category value,
  negative cost amount). Also verified by **real execution**: started the
  actual `uvicorn` process locally, hit `/health` (200), a real
  nonexistent-RO lookup through the live DB connection (404, read-only,
  touched 0 rows — matches production's confirmed 0-job-rows state), and
  `/docs` (200, FastAPI's auto-generated OpenAPI UI) before shutting the
  process down. Not left running.
- **Not yet built in the app layer:** no frontend, no authentication/
  session handling (ties to the still-pending receptionist permission
  question — see `app/api.py`'s header for why route-guards aren't wired
  yet even though DB-level capability enforcement already exists), no CSV
  upload UI (CLI only for now).

- **New this cron cycle (2026-09-06, later):** `app/models.py` gained a
  `StaffUser` dataclass (mirrors `collision.staff_user`, migrations 004
  + 009) with `__post_init__` domain validation matching migration 009's
  CHECK constraint — rejects a wrong/lookalike Google Workspace domain in
  Python before it ever reaches a query, same discipline as `Estimate`.
  `app/repository.py` gained the staff-provisioning functions closing the
  gap flagged 2026-09-06 as backlog ("staff provisioning should also
  create a `platform.person` row" — the schema-level requirement already
  existed via migration 004's FK, but no function exercised it):
  `provision_staff_user_for_existing_person()` (safe under `collision_app`
  — only touches `collision.staff_user`), `provision_new_staff_user()`
  (privileged-connection convenience wrapper creating both the
  `platform.person` and `staff_user` rows in one transaction, same
  pattern/limitation as `create_person_and_customer()`),
  `set_staff_user_active()`, `get_staff_capability()` (calls
  `collision.staff_user_capability()` from migration 007), and
  `get_estimates_for_job()` / `get_latest_estimate_for_job()` — closes a
  separate real gap: `collision.estimate` had a writer
  (`create_manual_estimate()`) but no reader anywhere in the repo.
  Verified by **real execution** against staging
  (`scripts/_smoke_staff_provisioning.py`): provisioned a real
  `staff_user` row, confirmed duplicate-provisioning correctly rejected,
  confirmed `get_staff_capability()` returns `'full'` while active and
  `None` after deactivation and back to `'full'` on reactivation (the
  same lever `verify_007.sql` exercises, now available as a real
  function), confirmed the Python-side domain check rejects a `gmail.com`
  address — then rolled back and confirmed by direct post-rollback query
  that zero `staff_user` rows persisted on staging. 3 new unit tests in
  `test_models.py` (wrong domain rejected, lookalike domain rejected,
  correct domain accepted + email lowercased) — `test_models.py` now
  15/15, `test_api.py` still 13/13, `test_pdr_settlement.py` still 7/7,
  no regressions.

- **New this cron cycle (2026-09-06, continuous-build):** wired the
  estimate/staff repository functions from the previous cycle into real
  HTTP routes on `app/api.py` — the natural next step that cycle's own
  "Next up" section flagged. Added: `GET /jobs/{ro_number}/estimates`,
  `GET /jobs/{ro_number}/estimates/latest`, `POST /staff` (provisions an
  existing person as staff — deliberately does NOT expose
  `provision_new_staff_user()`, which needs a privileged non-`collision_app`
  connection app/api.py has no way to supply safely today), `GET
  /staff/{google_email}`, `GET /staff/{google_email}/capability`, `POST
  /staff/{google_email}/active`. Same no-auth-yet scope decision as every
  other route in this file. 13 new tests in `test_api.py` (happy path +
  404s + bad-enum/duplicate 400s for each new route) — `test_api.py` now
  26/26, full suite 48/48. Verified by **real execution**: started the
  actual `uvicorn` process, hit `GET /jobs/RO-DOES-NOT-EXIST/estimates`
  and `GET /staff/nobody@completecollisions.com`(`/capability`) through
  the live production DB connection (all real 404s, read-only, 0 rows
  touched), then wrote `scripts/_smoke_api_estimates_staff.py` and ran it
  against real staging (built via the SAME repository functions the
  routes call — `create_customer_for_existing_person`,
  `get_or_create_vehicle`, `get_or_create_site`, `create_repair_order`,
  `create_manual_estimate`, the staff-provisioning functions — under `SET
  ROLE collision_app`, the real access pattern): provisioned a real
  staff_user, confirmed capability flips full/NULL on deactivate,
  inserted 2 real estimate versions and confirmed `get_estimates_for_job`
  returns them in order and `get_latest_estimate_for_job` returns the
  newest, confirmed an unknown RO returns `[]` rather than erroring — then
  rolled back and independently re-queried staging to confirm 0 rows
  persisted. Server process confirmed killed afterward (verified via
  `netstat`, not just the kill command's exit code — the launcher PID and
  uvicorn's actual listening worker PID differ on this host, first kill
  attempt missed the real listener).

## Deploy process (once schema work resumes)

Same discipline as VLS/Elektrica: every migration applied to the Neon
`staging` branch first, verified with a companion `scripts/verify_NNN.sql`
by direct query, staging reset to a clean mirror of production, then
promoted, tagged on promotion.

**Shared-staging caveat (per hermes, 2026-09-04):** the `staging` branch
on project `aged-art-92489373` is shared by all three build tracks (VLS,
Elektrica, Complete Collision). Each track resets staging from production
before its own migration tests, which can wipe another track's
in-progress test data or uncommitted staging-only schema state (nothing
is permanently lost — migration SQL and verify scripts are committed to
each repo's git history). Practical rule adopted here: **always re-run a
direct schema check against staging immediately before promoting**,
rather than trusting an earlier verification run if any time has passed
— another track's reset could have changed staging state in between.

## Open questions blocking further schema work

See `docs/ADR-001-complete-collision.md` §6.

## Not yet built

- **Migration 006 review** (`collision.site`, `collision.cost_entry`,
  written by a separate concurrent session — see WORKLOG.md's
  2026-09-04 "concurrent-session collision" entry) — awaiting Jed's
  answer on one specific product question: should `job`'s flat cost
  columns eventually become fully derived from `cost_entry`, or coexist?
  Not decided solo per hermes's 2026-09-04 instruction. Otherwise the
  migration reads as solid, reviewable work per hermes's independent
  read of it.
- `valid_next_states()`-style transition enforcement on `collision.job`
  — **RESOLVED** by `migrations/008_collision_job_valid_transitions.sql`
  (a DB-level trigger, `collision.job_status_forward_only()`), see the
  Schema section above.
- `collision.estimate` writers for `ccc_one_webhook`/`ai_proposed`
  sources (the shape exists; nothing writes to it yet — Phase 2/3, see
  migrations/003_collision_estimate.sql header)
- **`content_manifest.json` data import** — schema exists
  (`collision.content_item`), but the actual export lives on "the mini"
  (no access — see ADR-001 §2). Handoff §2.5's full migration discipline
  (export raw → inspect real keys → normalise → provenance → verify by
  aggregate) can't run until that export is obtainable.
- Content engine: per-job before/after generation, engagement-pull-back
  integration (Phase 2, per handoff §3.2-3.3)
- Backend/API server, frontend

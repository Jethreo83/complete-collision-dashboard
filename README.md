# Complete Collision Dashboard

Operational dashboard for Complete Collision & Auto Repair LLC. See
`docs/ADR-001-complete-collision.md` (approved by Jed, 2026-09-03, with
Phase 3 conditionally blocked) for scope, architecture, and data model.

## Status (as of migration 005 in production, migration 006 staging-only pending review, 2026-09-04)

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
- **Not yet built in the app layer:** no HTTP/API server, no frontend, no
  authentication/session handling (ties to the still-pending receptionist
  permission question), no CSV upload UI (CLI only for now).

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

- **Receptionist permission boundaries** — PENDING, logged for Jed in
  vls-dashboard's `docs/OVERNIGHT_DECISIONS.md` per hermes (2026-09-04).
  `collision.staff_user` (role enum + provisioning shape) exists;
  wiring real RLS/route-guard permission checks per role is explicitly
  deferred until that answer comes back.
- `valid_next_states()`-style transition enforcement on `collision.job`
  (currently append-only log, no SQL-level state-machine constraint — see
  migrations/002_collision_job.sql's SIMPLIFICATION note)
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

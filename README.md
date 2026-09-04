# Complete Collision Dashboard

Operational dashboard for Complete Collision & Auto Repair LLC. See
`docs/ADR-001-complete-collision.md` (approved by Jed, 2026-09-03, with
Phase 3 conditionally blocked) for scope, architecture, and data model.

## Status (as of migration 003, tag `collision-migration-003`)

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

- Staff auth/roles (owner/manager/receptionist), per ADR-001 §4
- `valid_next_states()`-style transition enforcement on `collision.job`
  (currently append-only log, no SQL-level state-machine constraint — see
  migrations/002_collision_job.sql's SIMPLIFICATION note)
- `collision.estimate` writers for `ccc_one_webhook`/`ai_proposed`
  sources (the shape exists; nothing writes to it yet — Phase 2/3, see
  migrations/003_collision_estimate.sql header)
- Content library migration, engagement-pull-back integration
- Backend/API server, frontend

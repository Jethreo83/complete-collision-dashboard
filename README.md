# Complete Collision Dashboard

Operational dashboard for Complete Collision & Auto Repair LLC. See
`docs/ADR-001-complete-collision.md` (approved by Jed, 2026-09-03, with
Phase 3 conditionally blocked) for scope, architecture, and data model.

## Status

**No backend/API/frontend exists yet.** Following the same build-order
discipline as VLS and Elektrica: schema and core business logic first.

### Schema — NOT YET APPLIED to any Neon branch

- `migrations/001_collision_customer.sql` — `collision.customer` (party
  table keyed to `platform.person`, identical pattern to `vls.client` and
  `elektrica.renter`) + RLS policy on `platform.person` for a
  `collision_app` role. Companion `scripts/verify_001.sql` written but not
  run.
- **Held, not applied:** the Neon project both VLS and Elektrica share
  (`aged-art-92489373`) is named "Jocasta Dashboard" in the Neon console.
  This bot's standing instructions treat the VLS/Jocasta boundary as
  absolute and require asking Jed directly before touching anything
  VLS-adjacent — including sharing a Postgres project/credential surface
  with `vls.client`. Elektrica's bot got a similar question resolved
  ("the VLS boundary is about case DATA, not schema/SQL with zero client
  data" — see `elektrica-dashboard/docs/BUILD_LOG.md`), which is
  encouraging precedent but was given to a different bot for a different
  schema. Waiting on Jed's direct confirmation (not just a relayed
  "proceed") before running `neon ... psql -f migrations/001_....sql`
  against that project. See `WORKLOG.md` for the live status of that ask.

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

## Open questions blocking further schema work

See `docs/ADR-001-complete-collision.md` §6, plus the Neon-project-sharing
question above (not yet in the ADR, tracked here and in `WORKLOG.md`).

## Not yet built

- `collision.job` (RO tracker — the spine, per ADR-001 §5 build order item 5)
- `collision.estimate` (manual + webhook-proposal + AI-draft versions)
- Staff auth/roles (owner/manager/receptionist), per ADR-001 §4
- Content library migration, engagement-pull-back integration
- Backend/API server, frontend

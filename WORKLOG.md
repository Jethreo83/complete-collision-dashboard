Complete Collision — Work Log
==============================

2026-09-03
- Read SOUL.md (first run). Reviewed available context files on disk to
  ground the plan in real facts before drafting anything (CCC ONE Master
  License Agreement, draft PDR Crew Operating Agreement, Elektrica/
  Complete Collision Operating Agreement). Wrote PLAN.md (ADR-001 draft)
  in a local-only repo at C:\Users\jedgr\Documents\complete-collision-
  dashboard (never pushed).

2026-09-04
- hermes relayed: repo is actually github.com/Jethreo83/complete-
  collision-dashboard. Cloned it fresh to Documents/complete-collision-
  dashboard-live. hermes had merged my license-text findings into
  docs/ADR-001-complete-collision.md, APPROVED by Jed (2026-09-03), Phase 3
  conditionally blocked on the CCC ONE license question. My original
  PLAN.md/WORKLOG.md preserved as docs/original-bot-plan.md /
  docs/original-bot-worklog.md.
- Investigated the "unexplained CCC ONE webhook" action item. Found
  CC_INVENTORY.md is addressed "CLAUDE_TO_KAY_007" — a handoff to
  kay-successor describing a system on "the mini" this bot has zero
  access to (confirmed: searched entire Windows host, nothing exists
  here). Messaged kay-successor directly rather than fabricate an answer;
  hermes confirmed the routing was correct.
- Cloned elektrica-dashboard-ref locally (read-only reference) to copy its
  exact migration/RLS/verify-script conventions: migrations/
  001_elektrica_renter.sql, scripts/verify_001.sql, docs/BUILD_LOG.md,
  README.md.
- Looked up the Neon project ID hermes gave (aged-art-92489373) myself via
  `neonctl projects list --api-key $NEON_API_KEY` before writing anything
  into it. Found it named "Jocasta Dashboard" in the Neon console — the
  VLS project. My standing instructions treat "no relationship to
  VLS/Jocasta" as an absolute boundary requiring Jed's direct confirmation,
  not an assumption or a relayed "proceed." Held the migration, wrote it
  with an explicit banner explaining why, and pressed hermes for
  verbatim confirmation rather than accepting a paraphrase — asked twice
  after the first two relays were truncated/generic.
- **Resolution:** hermes provided Jed's exact clickable selection,
  verbatim: "Same Neon project as VLS/Elektrica, new `collision` schema."
  This explicitly names VLS in the option Jed selected, satisfying the
  concern — Jed knowingly chose to share infrastructure with VLS
  specifically. Proceeded.
- Wrote migrations/001_collision_customer.sql (collision.customer party
  table + RLS on platform.person, identical pattern to vls.client /
  elektrica.renter) and scripts/verify_001.sql (6 checks, mirrors
  elektrica's verify_001.sql structure).
- Wrote scripts/run_sql.py — a small psycopg2-based runner (psql is not
  installed on this host; used `uv run --with psycopg2-binary`) that
  applies a .sql file statement-by-statement over a real connection,
  printing every RAISE NOTICE and every SELECT's actual result rows, so
  verification is by real query output, not exit-code trust. Iterated on
  its statement-splitter twice: first bug (crashed on a lone `--` comment
  producing an "empty query"), second bug (a semicolon appearing inside a
  `--` comment string was treated as a statement terminator, producing a
  syntax error) — both fixed and confirmed working before touching the
  real database.
- Full staging → verify → reset → promote cycle, same discipline as
  Elektrica's migration 001:
  1. Pre-check on staging (`neondb_owner`/staging branch
     br-broad-hat-a5uyz6he): confirmed `collision` schema and
     `collision_app` role did NOT exist yet, only `platform`, `vls`,
     `elektrica` schemas and `vls_app`/`elektrica_app` roles present.
  2. Applied migrations/001_collision_customer.sql to staging —
     COMMITTED, no errors.
  3. Ran scripts/verify_001.sql against staging — all 6 checks passed by
     real output: CHECK 1 showed 2 person rows (owner sees all), CHECK 2
     showed exactly 1 row (CustomerPerson only, NonCustomerPerson
     genuinely absent under collision_app role), CHECK 3 NOTICE "PASSED:
     collision_app blocked from INSERT on platform.person", CHECK 4
     showed 2 rows under platform_identity_service (bypasses RLS), CHECK
     5 showed 1 row for collision_app reading its own schema, CHECK 6
     NOTICE "PASSED: customer_one_row_per_person constraint enforced".
  4. Reset staging to a clean mirror of production
     (`neonctl branches reset staging --parent`), polled until state
     returned to "ready".
  5. Re-ran the pre-check against the freshly reset staging branch:
     confirmed `collision` schema and role were gone again, test rows
     gone — staging genuinely reset, not just reported as reset.
  6. Applied migrations/001_collision_customer.sql to PRODUCTION
     (br-dawn-resonance-a5xfpgqv) — COMMITTED.
  7. Ran the same pre-check query against production: confirmed by direct
     query that `collision` schema, `collision_app` role, and
     `collision.customer` table are all live on production.
  8. Tagged the repo `collision-migration-001` and pushed the tag.
- This is the FIRST real database change this bot has made — verified at
  every step by direct query output, matching the VLS/Elektrica
  discipline exactly, including the specific extra step (Jed's explicit,
  VLS-naming confirmation) required by this bot's own hard boundary.
- Wrote and ACTUALLY RAN pdr_settlement.py (PDR Crew monthly settlement
  calculator implementing the 70/30 / 5/95 / 40/60 splits from the draft
  Operating Agreement) plus test_pdr_settlement.py (7 tests, all passed
  on real execution) and example_statement.py (ad-hoc realistic example,
  output inspected). No CCC ONE or DB dependency — safe to build and test
  independent of the Neon-project question, done in parallel while that
  was pending.
- Updated README.md and this file to reflect the real, verified state.
  Removed the now-stale "NOT YET APPLIED" banners from the SQL files
  themselves once the migration was actually promoted.
- Committed and pushed to github.com/Jethreo83/complete-collision-
  dashboard, tag collision-migration-001.

Files touched this session (in complete-collision-dashboard-live, the
canonical repo):
- migrations/001_collision_customer.sql (created, applied to staging then
  production, both confirmed by direct query)
- scripts/verify_001.sql (created, run against staging — 6/6 checks
  passed)
- scripts/run_sql.py (created — SQL-file runner used for all of the
  above, no psql binary available on this host)
- pdr_settlement.py (created, tested)
- test_pdr_settlement.py (created, run: 7/7 passed)
- example_statement.py (created, run, output verified by inspection)
- README.md (updated twice — once to reflect the held state, once to
  reflect the completed promotion)
- WORKLOG.md (this file)

Files touched in Documents/complete-collision-dashboard (my original,
now-historical local repo): none this session — superseded by the
GitHub repo per hermes's 2026-09-04 instruction.

Files touched in Documents/elektrica-dashboard-ref: none — read-only
reference clone, not part of this repo, not committed to.

Neon infrastructure touched (not files, but recording for the audit
trail Jed asked for): staging branch br-broad-hat-a5uyz6he (applied,
verified, reset), production branch br-dawn-resonance-a5xfpgqv (applied,
confirmed live) — both on project aged-art-92489373 ("Jocasta Dashboard"
in console).

Open, tracked separately (not blocking further Phase 1 work):
1. Everything in docs/ADR-001-complete-collision.md §6 (receptionist
   permissions, which CCC ONE data mechanism is licensed, PDR Crew
   draft-vs-signed timing, whether an accounting system feeds RO costs).
2. kay-successor's report on the 4 cccone_logs payload contents (asked,
   not yet received).

Next up: collision.job (the RO tracker spine, per ADR-001 §5 build order
item 5), same staging → verify → promote discipline.

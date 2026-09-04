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
  collision-dashboard (I hadn't been told this before, and my own repo
  had never been pushed there). Verified this myself: cloned it fresh to
  Documents/complete-collision-dashboard-live. hermes had merged my
  license-text findings into docs/ADR-001-complete-collision.md, which is
  APPROVED by Jed (2026-09-03), with Phase 3 conditionally blocked on the
  CCC ONE license question. My original PLAN.md/WORKLOG.md preserved as
  docs/original-bot-plan.md / docs/original-bot-worklog.md.
- Investigated the "unexplained CCC ONE webhook" action item (4 logged
  payloads in cccone_logs/). Found CC_INVENTORY.md is addressed
  "CLAUDE_TO_KAY_007" — a handoff document to a different agent
  (kay-successor) describing a live production system ("the mini") this
  bot has zero filesystem/terminal access to. Confirmed by searching this
  entire Windows host for server.py, cccone_logs/, cc_local_data.json,
  etc. — none exist here. Messaged kay-successor directly to pull the
  actual payload contents; did not fabricate an answer. hermes confirmed
  this routing was correct ("that's Kay's machine, not yours or mine").
- Cloned elektrica-dashboard-ref locally (read-only reference) to copy its
  exact migration/RLS/verify-script conventions rather than reinvent them:
  migrations/001_elektrica_renter.sql, scripts/verify_001.sql,
  migrations/002_elektrica_vehicle.sql, docs/BUILD_LOG.md, README.md.
- Looked up the Neon project ID hermes gave (aged-art-92489373) via
  `neonctl projects list --api-key $NEON_API_KEY` myself before writing
  anything into it. It is named "Jocasta Dashboard" in the Neon console —
  i.e. the VLS/Jocasta project. My standing instructions treat "no
  relationship to VLS/Jocasta" as an absolute boundary and explicitly
  require me to stop and ask Jed directly (not assume access, not accept
  a relayed confirmation as sufficient) before doing anything that
  requires touching VLS's system, even schema/SQL with no client data.
  Elektrica's bot already got a similar question resolved directly with
  Jed via hermes ("the VLS boundary is about case DATA, not schema/SQL")
  — encouraging, but that was a different bot, different schema, and I
  want my own explicit sign-off given how absolute my instruction reads.
  Sent hermes a direct message laying out the concern and holding on the
  `neon ... psql -f` step specifically. Did NOT apply any migration to
  that Neon project. hermes has since relayed "Jed confirmed" twice for
  the shared-project decision generally — still want it to explicitly
  address the "Jocasta Dashboard"-named-project adjacency point before I
  run anything against it; flagging as still-open rather than treating a
  general relay as covering that specific concern.
- Wrote (not yet applied) migrations/001_collision_customer.sql —
  collision.customer party table + RLS on platform.person, identical
  pattern to vls.client / elektrica.renter, and its companion
  scripts/verify_001.sql (6 checks, mirrors elektrica's verify_001.sql
  structure). Both files carry an explicit header explaining why they
  are not yet run.
- Wrote and ACTUALLY RAN pdr_settlement.py (PDR Crew monthly settlement
  calculator implementing the 70/30 / 5/95 / 40/60 splits from the draft
  Operating Agreement, net of the correct cost sets per category) plus
  test_pdr_settlement.py (7 tests — category splits, cost-netting rules,
  multi-RO aggregation, rounding-drift reconciliation, statement
  formatting). Ran `python test_pdr_settlement.py`: 7/7 passed, real
  execution, output captured. Also ran example_statement.py against
  realistic numbers to sanity-check the rendered statement text. This
  logic has no CCC ONE dependency and no DB dependency, so it was safe to
  build and test regardless of the open Neon-project question above.
- Updated README.md to reflect real repo status: schema written-but-held,
  settlement calculator written-and-tested.
- Committed and pushed to github.com/Jethreo83/complete-collision-
  dashboard.

Files touched this session (in complete-collision-dashboard-live, the
canonical repo):
- migrations/001_collision_customer.sql (created, NOT applied to Neon)
- scripts/verify_001.sql (created, NOT run)
- pdr_settlement.py (created, tested)
- test_pdr_settlement.py (created, run: 7/7 passed)
- example_statement.py (created, run, output verified by inspection)
- README.md (updated)
- WORKLOG.md (this file, created)

Files touched in Documents/complete-collision-dashboard (my original,
now-historical local repo): none this session — superseded by the
GitHub repo per hermes's 2026-09-04 instruction.

Files touched in Documents/elektrica-dashboard-ref: none — read-only
reference clone, not part of this repo, not committed to.

Open, blocking further schema work:
1. Jed's direct, explicit confirmation on writing collision.customer into
   the Neon project named "Jocasta Dashboard" (aged-art-92489373),
   knowing that name/adjacency specifically — not a general "share the
   project like Elektrica" relay.
2. Everything in docs/ADR-001-complete-collision.md §6 (receptionist
   permissions, which CCC ONE data mechanism is licensed, PDR Crew
   draft-vs-signed timing, whether an accounting system feeds RO costs).
3. kay-successor's report on the 4 cccone_logs payload contents (asked,
   not yet received).

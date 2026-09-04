# Shared conventions (Jed's integrator, relayed via hermes 2026-09-04)

Full source: `vls-dashboard/docs/SHARED_CONVENTIONS.md` (private repo —
this bot has no direct read access, per its standing VLS boundary;
content below was pasted by hermes on request, confirmed not sensitive).
Every locked domain bot (VLS, Elektrica, Complete Collision) builds
against these six shared primitives rather than reinventing them.

1. **Person registry** — `platform.person` stays thin; each project owns
   its own party table + RLS. Complete Collision: `collision.customer`
   (migration 001) — already correct, built before this doc was known,
   independently converged on the same pattern as `vls.client` /
   `elektrica.renter`.
2. **Document generator** — ONE shared primitive:
   `(template_id, template_version, merge_data, attachments[]) -> PDF +
   generation_log_row`. Every project calls it, none builds its own.
   **Resolved 2026-09-04 (hermes, direct):** `pdr_settlement.py` does
   NOT violate this — it's pure computation (profit-split formula
   producing numbers), not document rendering, same category as
   `vls.settlement_breakdown`. If/when Complete Collision needs an
   actual PDF settlement statement (not just the numbers), THAT step
   goes through the shared generator once it exists; the computation
   stays here. Any future document-producing feature (PDR Crew
   statements as real PDFs, marketing captions, demand-letter-adjacent
   work if it ever arises) must call the shared generator, not build a
   parallel one.
3. **State-machine engine** — one append-only `case_event` pattern, JP
   logic lives once in VLS, reused not forked. Not directly relevant to
   Complete Collision unless it ever needs litigation state (unlikely).
   `collision.job_event` (migration 002) is this project's own
   append-only event log for job-status transitions — same pattern
   family, own domain, not a fork of VLS's JP-specific logic.
4. **Communication/inbox bot** — one inbound-match-then-propose
   primitive, never auto-file. Matches this project's existing CCC ONE
   webhook caution exactly (ADR-001 §2: inbound payloads should land as
   proposals on the matching job, never applied directly — not yet
   built, webhook not yet authenticated, per the still-open payload
   inspection question).
5. **Payments** — one table shape, `accounting_sync_ref` reserved for
   later. Not yet built for Complete Collision (handoff §2.3 lists
   `payment` as shared shape with Elektrica — apply this convention when
   that table is designed).
6. **Bot interface** — bot writes only via scoped API key to proposal
   endpoints, propose-then-confirm. Relevant once the CCC ONE webhook is
   authenticated (ADR-001 §6 action item 2) and for any future email/
   adjuster bot (handoff §4.2, already scoped this way in the handoff's
   own design).

## Marketing / posting engine note (phase 2, but binding now)

Per Jed (relayed 2026-09-04): the marketing dashboard explicitly says
"promote Collision's existing posting engine (Kay's `server.py`) into a
shared service, don't rebuild it." Whenever this project's posting/
content-library work reaches Phase 2, that's the constraint — extend/
promote the existing engine, not a fresh build. `collision.content_item`
(migration 005) is schema-only and does not conflict with this (it's a
destination table for manifest data, not a posting engine).

Financials and brain-console dashboards are Phase 2 hold, regardless of
convention readiness.

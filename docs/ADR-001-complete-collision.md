# ADR-001: Complete Collision Dashboard — Architecture & Scope

Status: **APPROVED by Jed, 2026-09-03**, with Phase 3 conditionally blocked
per §1. Folds in Claude's COMPLETE_COLLISION_HANDOFF_2026-09-03.md, Kay's
CC_INVENTORY.md findings, the complete-collision bot's own legal finding
(CCC ONE license restriction), and Jed's direct answers (2026-09-03).

## 1. A legal constraint the handoff did not know about

The complete-collision bot's shared memory contains a finding that changes
Phase 3 (and touches Phase 1) of the handoff design:

**CCC ONE's Master License Agreement restricts data use**: no aggregating
estimate data into a database, no reports/analysis "to anyone", no 3rd-party
apps using CCC ONE data without CCC's written approval, no bots entering
data. This is a contractual restriction with CCC Intelligent Solutions, not
a technical limitation.

**Confirmed against the actual license text** (complete-collision bot read
the signed contract directly — `Complete Collision & Auto Repair LLC_CCC
contract_4.27.26.pdf`, Section 2.4): the agreement prohibits compiling
estimate data into a database, aggregating/co-mingling CCC ONE data or
providing reports/analysis based on it "to anyone," incorporating
third-party applications or using CCC ONE data in any application not
owned by CCC "without the prior written approval of CCC," and using
automation bots/scripts to enter data into CCC ONE.

**Four named data-sharing mechanisms exist in the license** (bot's finding,
citing specific sections) — each may have different permitted uses:
EMS Extract (Section 25), CCC Secure Share Network (Section 26), CCC-DMS
Interface (Section 34), CCC Indicators/Estimatic Reports (Section 27).
**Jed needs to confirm which of these is actually licensed/active on the
Complete Collision account** — this is more actionable than the original
"get CCC's written approval" framing, since one of these named paths may
already be permitted under the existing contract.

**Effect on the handoff's design:**
- Phase 1's "hand-port CCC ONE estimates into the dashboard" (handoff §2.1,
  §2.4) is a **human re-entering data they already have access to** — this
  is very likely fine (it's how the business already operates: manual
  re-entry, not extraction), but has not been confirmed against the actual
  license language. **Do not proceed past a "CCC ONE view for fast manual
  copy" UI without Jed confirming with counsel or CCC directly that manual
  human re-entry, with no automated read/write against CCC ONE, is
  permitted.**
- The inbound webhook (`/api/cc/cccone-webhook`) already existing and firing
  is now a bigger question than "authenticate it" (CC handoff §6 item 2) —
  **whether that webhook should exist at all** depends on what it does with
  the data once received. If it's aggregating CCC ONE estimate data into
  `cc_local_data.json` or any dashboard table, that may itself violate the
  license. This needs the payload contents inspected (see §2 below) before
  the webhook is even authenticated, let alone kept.
- Phase 3's AI estimator (handoff §5) — training an AI on CCC ONE-derived
  estimate data and using it to "write the estimate" is the license
  restriction's most direct target ("no bots entering data", "no
  reports/analysis"). **Phase 3 as scoped in the handoff may not be legally
  buildable without CCC's written approval.** This is not an engineering
  question. Flagging as a hard blocker on Phase 3, not just a "later"
  phase — it may need to be redesigned around CCC ONE entirely, or
  formally cleared with CCC first.

**Action:** Jed to get a straight answer from CCC ONE (account rep or the
license itself) on: (a) is manual human re-entry into a separate system
permitted, (b) what does "no aggregating estimate data" actually prohibit
in practice, (c) is there an approved integration path (EMS Extract, Secure
Share, DMS Interface, CCC Indicators — mentioned in the bot's memory note)
that would legitimize any of this. Nothing in Phase 1 that touches CCC ONE
data should be built past a read-only, human-driven UI until this is
answered.

## 2. The unexplained webhook — needs inspection, not just authentication

Jed confirmed: **Complete Collision has never been able to configure CCC
ONE's API or webhooks.** Yet `/api/cc/cccone-webhook` has logged 4 real
payloads (per Kay's inventory). This is now a genuine anomaly:

- Either something Jed doesn't know about configured this (another
  employee, a CCC ONE feature enabled without Jed's awareness, a
  third-party integration), or
- The endpoint is unauthenticated (confirmed) and something unrelated to
  CCC ONE is hitting it — scanning, a misconfigured client elsewhere, or a
  stale integration from a source no longer in use.

**Action, before anything else in §6 of the CC handoff:** have Kay pull the
actual contents of the 4 logged payloads in `cccone_logs/` and report what
they contain (real CCC ONE-shaped data vs. junk/scan traffic vs. something
else entirely). This determines whether the webhook is a real integration
that needs the license question above answered, or dead/spurious traffic
that can simply be closed off.

## 3. Confirmed facts (Jed, 2026-09-03) — resolves handoff §7

| Handoff open question | Answer |
|---|---|
| Payments: own book of record, QuickBooks sync later? (CC-6) | **Confirmed**, with a specific mechanism: payments recorded/made via API show live in the dashboard; QuickBooks sync is a later, additive step — not built now. |
| Who uses the dashboard? | **Jed (owner), a manager, and a receptionist.** Not just Jed — this needs a real multi-role login system from v1, not a single-user assumption. Roles likely: owner (full), manager (operational, maybe financial), receptionist (front-desk: intake, scheduling, customer-facing status — probably not full financial/estimate access). Exact role boundaries are an open question (see §4). |
| CCC ONE webhook: native or configured? | **Never configured by Complete Collision.** See §2 above — this is now an open anomaly, not a closed fact. |
| Scanner vendor for Phase 3? | **UVEYE** — identified, not yet acquired/installed ("we don't have it"). This is real vendor information that unblocks Phase 3 scoping research (output format, integration method) even though the hardware isn't deployed yet. Do not build against UVEYE's format yet without confirming their actual output spec — but it's no longer an unknown vendor. |
| "Best content" measurement? | **Post engagement (likes/views/etc.)** — confirms Phase 2 needs engagement pull-back from each platform's API, not just manual rating. This is a real integration requirement for the content-library "by uploader over time" view (handoff §3.1), not a nice-to-have. |

## 4. Scope changes from the handoff given these answers

- **Roles/auth is now a v1 requirement, not deferred.** The handoff assumed
  a simpler access model. With owner + manager + receptionist all needing
  access, this needs the same staff_user + role pattern already proven in
  VLS migration 005 (Google Sign-In restricted to the business domain, role
  enum, admin-provisioned). Recommend three roles at minimum: `owner`,
  `manager`, `receptionist`, with receptionist likely read-mostly plus
  intake/scheduling write access — exact permission boundaries need Jed's
  input before the RLS/route-guard design is final.
- **Phase 2's engagement-pull-back requirement is now confirmed, not
  optional** — each platform integration (Facebook, Instagram, Google
  Business) needs its analytics/insights API wired, not just the posting
  API. This is more integration surface than the handoff's "generate +
  queue for one-click post" framing implied.
- **Phase 3 planning can start narrowly on UVEYE's actual capabilities**
  once Jed has their spec sheet or a sales conversation, but building
  anything is still blocked on: (a) the CCC ONE license question in §1,
  since the estimator's whole purpose is estimate content that touches
  CCC ONE workflows, and (b) months of confirmed-estimate training data
  from Phase 1 not existing yet (handoff §5, unchanged).

## 5. Build order (supersedes handoff §6 item ordering slightly)

1. **CCC ONE license clarification** (§1) — blocks nothing else immediately,
   but must resolve before Phase 1's "CCC ONE view" ships past internal
   testing, and fully blocks scoping Phase 3.
2. **Inspect the 4 webhook payloads** (§2) — cheap, fast, resolves a real
   unknown before deciding whether to authenticate or kill the endpoint.
3. Backup/auth-patch/key-rotation items from the original §6 list — already
   relayed to Kay, tracked separately, not blocking schema design.
4. Staff auth + roles (owner/manager/receptionist) — same pattern as VLS
   migration 005, needs Jed's input on exact receptionist permissions.
5. Tracker schema (handoff §2.3) + JSON migration (handoff §2.5) — proceed
   as designed, this doesn't touch CCC ONE data aggregation, only Complete
   Collision's own job/payment records.
6. Content library migration (handoff §3.1) + engagement-pull-back
   integration (now confirmed required, see §4).
7. Phase 2 bots (email/adjuster, handoff §4) — unchanged.
8. Phase 3 — blocked on §1 resolution and Phase 1 data accumulation, per
   handoff's own reasoning, now with UVEYE as a concrete target once
   acquired.

## 6. Open questions still remaining

1. Exact receptionist role boundaries — what should a receptionist see/edit
   vs. manager vs. owner?
2. Which named CCC ONE data-sharing mechanism (EMS Extract, Secure Share,
   DMS Interface, CCC Indicators) is actually licensed/active on Complete
   Collision's account? This is now the more actionable form of the CCC ONE
   license question — one of these may already be permitted under contract.
3. UVEYE integration spec (output format, delivery method) once available.
4. `CC Cristian` / `CC Operations` tabs — still live or legacy? (handoff §7
   item 6, unanswered this round)
5. Build against the current draft (unsigned, bracketed-terms) PDR Crew
   agreement now, or wait for signature?
6. Does an existing accounting system (QuickBooks etc.) feed Direct RO
   Costs / Labor Costs / Rent-Utilities for the settlement calc, or will
   those be entered manually?

## 7. New scope surfaced by the complete-collision bot's direct document review

The bot read source documents I did not have access to (the signed CCC ONE
contract, the draft Complete Collision/PDR Crew Operating Agreement, and
the Elektrica/Complete Collision Operating Agreement) and found concrete,
high-value scope beyond the original handoff:

- **PDR Crew monthly settlement automation** — real, recurring, currently
  manual accounting task. The co-branded "Complete Collision & PDR Crew"
  site splits every RO into one of three categories (Collision/PDR/Hail),
  each with its own profit-split formula (70/30, 5/95, 40/60 respectively,
  net of direct RO costs, and for Collision only, labor + rent/utilities).
  A monthly itemized statement is contractually due to PDR Crew within 10
  days of month-end, paid within 15 days. **This is a strong v1 candidate**
  — high value, well-specified by contract, not blocked by the CCC ONE
  license question if built against manually-entered RO cost data rather
  than live CCC ONE pull (see Phase 1 in §5 below).
- **The PDR Crew agreement is still in draft** (bracketed terms, unsigned)
  — Jed needs to decide whether to build against current draft terms and
  adjust later, or wait for signature.
- **Elektrica/Complete Collision Operating Agreement** confirms the
  rental-repair routing rule referenced in the Elektrica handoff (repair
  goes to the "Originating Shop") and separately contains a binding
  18-month option for Chris Raeder/Autocraft to buy 33% of Complete
  Collision, plus a non-solicit on Autocraft's OEM/fleet accounts (Rivian,
  Lucid, Porsche). **This is an ownership/legal constraint, not a
  dashboard feature** — noted only because it constrains what financial
  reporting might later become sensitive/discoverable in the KPI views.

## 8. Repo consolidation note

Two local copies of this project existed independently: one at
`AppData/Local/hermes/projects/complete-collision-dashboard` (this one,
pushed to `github.com/Jethreo83/complete-collision-dashboard`) and one at
`Documents/complete-collision-dashboard` (the bot's own workspace,
git-initialized but never pushed, containing `PLAN.md`/`WORKLOG.md` with
the license-text research folded into this ADR above). **The GitHub repo
is the canonical one going forward** — the bot has been redirected to work
there; its original local files are preserved as source material, not a
competing plan.

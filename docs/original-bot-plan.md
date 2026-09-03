ADR-001: Complete Collision Dashboard — Foundational Architecture
Status: PROPOSED — awaiting Jed's review and sign-off. No code written yet.
Date: 2026-09-03
Owner: Complete Collision bot (Hermes agent)

---

1. CONTEXT

Complete Collision & Auto Repair LLC (Austin, TX — South Site: 12110 Menchaca
Rd Ste 300) is a collision repair shop. Business facts gathered from Jed's
files that shape this plan:

- System of record today is CCC ONE (CCC Intelligent Solutions), licensed
  under an Automotive Services Master License Agreement (signed 4/27/26,
  36-mo term, auto-renews). Modules licensed: CCC Optimize Package 4.0
  (Estimating, Aftermarket, Documents, Tire, Recall, Paintless Dent Repair
  Review, Frame, UpdatePlus, Workflow Pro, KPI Dashboard, Checklist), CCC
  Build Sheets, CCC Pay Workflow.
- Complete Collision has a second, co-branded location ("Complete Collision
  & PDR Crew") operating under a draft Operating Agreement with PDR Crew.
  That agreement defines THREE work categories per repair order — Collision
  Work, PDR Work, Hail Work — each written to its own RO number series in
  CCC ONE, each with a different monthly profit split (70/30, 5/95, 40/60
  respectively) net of direct RO costs, and for Collision Work only, labor
  costs and rent/utilities. A monthly settlement statement itemized by RO,
  category, and site is contractually due to PDR Crew within 10 days of
  month-end, paid within 15 days of the statement. This is a real,
  recurring, error-prone manual accounting task today — a strong first
  candidate for the dashboard to automate or at least materially speed up.
- Complete Collision and Elektrica Holdings LLC (Jed's rental company) have
  an Operating Agreement covering repair routing for damaged rental
  vehicles (repair goes to the "Originating Shop" that rented the vehicle)
  and referral of Elektrica rental customers' own accident repairs back to
  the Originating Shop. This is the cross-business link the SOUL.md shared
  memory is meant to support — e.g. "this customer also rented from
  Elektrica."
  - Also present in that agreement (informational, not necessarily in
    dashboard scope): a binding 18-month purchase option granting Chris
    Raeder / an Autocraft entity the right to buy 33% of Complete Collision
    at a price tied to YTD profits, and a non-solicitation clause barring
    Complete Collision from pursuing Autocraft's OEM/fleet accounts
    (named: Rivian, Lucid, Porsche). Flagging both as constraints on any
    future CRM/lead-gen feature and on financial reporting exposure.
- Public web presence: completecollisions.com, SE Ranking audit score
  95/100 (health), a few minor SEO issues (missing favicon, no www
  redirect, unminified CSS, long titles/descriptions, missing Twitter
  card tags) — not urgent, noted as a possible small backlog item, not a
  dashboard architecture concern.

Net: the dashboard's most concrete, high-value job is operational/financial
visibility and automation on top of CCC ONE data, specifically the
multi-party RO-category profit split, plus general shop KPIs and
cross-business (Elektrica) context. Everything else (marketing/SEO,
website) is secondary.

---

2. WHAT THE DASHBOARD NEEDS TO DO (v1 candidate scope)

a. Repair order visibility: pull/import RO data (status, category, site,
   revenue, cost lines) from CCC ONE so Jed/staff have one screen instead
   of digging through CCC ONE reports.
b. PDR Crew monthly settlement automation: compute Monthly Net Profit per
   category (Collision / PDR / Hail) per the Operating Agreement formula,
   generate the itemized statement, track payment status. (Held for review
   — this pays a real third party, so any generated statement is
   draft-and-hold for Jed before it goes to PDR Crew, per standing rule.)
c. Shop KPIs: cycle time, RO volume/mix by category and site, revenue,
   comebacks — whatever CCC ONE's KPI Dashboard module already doesn't
   surface adequately for Jed's purposes (need to confirm what's missing
   vs. duplicated).
d. Cross-business context surface: flag/link ROs or customers that
   originated from an Elektrica rental, per the routing agreement, and
   make that visible to both bots' shared memory.
e. (Maybe, later) Basic customer/insurance claim status view, complementary
   to CCC UpdatePlus/Engage rather than replacing them.

Explicitly NOT in v1: marketing/SEO fixes, anything client-facing/
external, anything that touches CCC ONE data in a way its license
prohibits (see Open Questions — this is a hard gate, not a style choice).

---

3. PROPOSED ARCHITECTURE

- Single small web app, own repo (this one), separate from Elektrica's.
- Backend: lightweight API + scheduled sync jobs. Exact stack is flexible
  and I'll default to whatever matches Jed's other tooling for
  consistency, but absent a stated preference: Python (FastAPI) or
  Node (Express) backend, Postgres or SQLite (SQLite is fine at this
  scale and this Windows host) for storage, a simple server-rendered or
  lightweight SPA frontend. No need for a heavy framework at this size.
- Data flow: CCC ONE → (approved export/interface, TBD — see Open
  Questions) → local database → dashboard reads from local DB. The
  dashboard is a reporting/automation layer, not a replacement for CCC
  ONE, and does not re-implement estimating or write back into CCC ONE
  unless/until that's explicitly wanted and confirmed as license-safe.
- Hosting: local-first (runs on Jed's machine / a small always-on box),
  same posture as the other Hermes-run dashboards. No external deployment
  or public exposure without Jed's explicit sign-off, per standing rule.
- Auth: single-user or small-staff login; no public internet exposure
  planned for v1.

---

4. DATA MODEL (draft, subject to change once CCC ONE export shape is known)

- Site: id, name (South/North), address
- RepairOrder: id, ro_number, site_id, category (collision/pdr/hail),
  status, opened_at, closed_at, collected_at, customer_id, vehicle_id,
  insurer (nullable), gross_revenue, direct_ro_costs
- Customer: id, name, contact info, source (walk-in / insurer / elektrica
  rental / referral), linked_elektrica_customer_id (nullable — cross-
  business link)
- Vehicle: id, vin, make, model, year, customer_id
- LaborCost / RentUtility: monthly entries feeding Collision Work profit
  calc (per Operating Agreement 4.4/4.5)
- MonthlySettlement: id, month, category, site_id, computed_net_profit,
  cc_share, pdr_share, statement_generated_at, paid_at, status
  (draft/held-for-review/sent/paid)
- KpiSnapshot: periodic rollups for dashboard charts (cycle time, RO
  volume/mix, revenue) — derived, not source-of-truth.

---

5. INTEGRATIONS

- CCC ONE (CCC Intelligent Solutions) — primary system of record. Method
  TBD: the Master License Agreement references several possible data
  paths — EMS Extract (Section 25), CCC Secure Share Network (Section
  26), CCC-DMS Interface (Section 34), CCC Indicators/Estimatic Reports
  (Section 27). Each has different permitted uses and restrictions. This
  needs Jed's input / CCC's confirmation before any integration code is
  written (see Open Questions #1 — this is the most important open item
  in this whole plan).
- Elektrica dashboard / shared memory — for cross-referencing rental-
  originated customers and repair routing, via the existing memory
  junction, not a live API (no need to over-engineer this yet).
- Possibly: CCC Pay Workflow or whatever underlies invoicing, if there's
  a reason to reconcile payments here rather than just reading status.
- Not integrating with anything client-facing (no email/SMS sending, no
  booking) in v1 — CCC UpdatePlus/Engage already cover that ground.

---

6. OPEN QUESTIONS (need Jed's answers before/while building)

1. CCC ONE data access — BLOCKING. The Master License Agreement (Sec 2.4)
   explicitly prohibits: compiling estimate data into a database,
   aggregating/co-mingling CCC ONE data or providing reports/analysis
   based on it "to anyone," incorporating third-party applications or
   using CCC ONE data in any application not owned by CCC "without the
   prior written approval of CCC," and using automation bots/scripts to
   enter data into CCC ONE. A dashboard that stores and reports on RO
   data pulled from CCC ONE brushes right up against several of these
   clauses. Before writing any integration code I need Jed to confirm:
   (a) which official CCC data-sharing mechanism (EMS Extract, Secure
   Share, DMS Interface, CCC Indicators) is actually licensed/available
   on this account, and (b) whether CCC's written approval is needed/
   obtainable for a custom reporting app, or whether all dashboard data
   entry will instead be manual/CSV-based to sidestep this entirely for
   v1. I will not build any automated CCC ONE scraping or bot-driven data
   entry regardless of the answer — that's a flat license violation, not
   just a risk.
2. Tech stack preference — does Jed want this to match the Elektrica
   dashboard's stack for shared maintenance, or is there no constraint?
3. Who are the actual dashboard users — just Jed, or shop staff/managers
   too? Affects auth/roles.
4. PDR Crew agreement is still in draft (bracketed terms, unsigned per
   the copy on file) — should the settlement-automation feature wait
   until it's finalized, or build against the current draft terms and
   adjust later?
5. Does Jed want any write-back to CCC ONE ever, or is this strictly a
   read/report layer indefinitely?
6. Hosting: confirmed local-only for now — any timeline where remote
   access (e.g. from a phone) becomes a requirement, which would change
   the auth/exposure story?
7. Is there an existing accounting system (QuickBooks etc.) that should
   feed Direct RO Costs / Labor Costs / Rent-Utilities, or will those be
   entered manually into the dashboard?

---

7. NON-GOALS (for now)

- Not a competitor to CCC ONE's estimating/workflow features.
- Not a customer-facing portal or messaging tool.
- Not handling Elektrica's own rental operations (that's Elektrica's
  dashboard's job — this bot only surfaces the cross-business link).
- Not touching anything related to the Autocraft/Chris Raeder equity
  option directly (that's a legal/ownership matter for Jed and counsel,
  not a dashboard feature) — noted only because it constrains what kind
  of financial reporting might later become sensitive/discoverable.

---

8. ROLLOUT (once approved)

Phase 0: resolve Open Question #1 (CCC ONE data access) with Jed.
Phase 1: manual/CSV-based RO tracking + PDR Crew settlement calculator,
no live CCC ONE integration — proves out the data model and the
settlement math against the real Operating Agreement formula.
Phase 2: automate data pull via whichever CCC ONE mechanism is confirmed
license-safe.
Phase 3: KPI dashboard, cross-business linkage with Elektrica.

No deployment, external exposure, or automated communication to PDR Crew,
CCC, or customers happens without Jed's explicit sign-off at each step.

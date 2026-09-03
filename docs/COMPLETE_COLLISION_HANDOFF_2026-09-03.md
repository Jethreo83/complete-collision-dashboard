# COMPLETE COLLISION HANDOFF — 2026-09-03

**From:** Claude (design review)
**For:** Jocasta (build), Kay (operations / export), Jed Grant (decisions)
**Companions:** `VLS_DASHBOARD_HANDOFF_2026-09-02.md` (ADRs, verification standard, agent lanes) and `ELEKTRICA_HANDOFF_2026-09-03.md` (shared primitives §1, which this document reuses by reference).

**Sources:** Jed's spoken description (2026-09-03) **and** Kay's static-analysis inventory `CC_INVENTORY.md` (CLAUDE_TO_KAY_007, verified md5 `32a5067a…`). Unlike the Elektrica handoff, this one was written *after* the code inventory, so Kay's findings are integrated rather than appended. Row counts, headers, and field fill rates remain **PENDING AUTH** until Google OAuth is restored on the cloud host.

Contains no secrets and no client names.

---

## 0. Decisions locked

| # | Decision | Status |
|---|---|---|
| CC-1 | Complete Collision is **two systems sharing a vehicle**: a repair-and-collections tracker, and a content engine. Designed and phased separately. | Approved |
| CC-2 | **Three-phase build, and the phases are dependencies, not preferences.** Phase 1 tracker + library migration → Phase 2 email/adjuster bot + content generation with human-shipped posting → Phase 3 scanner + AI estimator. Each phase manufactures what the next consumes. | Approved |
| CC-3 | CCC ONE: **no API, no outbound integration.** Inbound webhook exists (Kay 007). Design for fast manual re-entry outbound; accept inbound pushes as proposals. AI never drives the CCC ONE UI in this build. | Approved |
| CC-4 | AI estimating is **propose-and-confirm**: the AI produces estimate content laid out for fast entry; a human estimator reviews with the AI's assumptions visible; both the AI draft and the confirmed estimate are stored. | Approved |
| CC-5 | Bot-drafted outbound to adjusters is human-sent, or tightly templated status requests only, every one logged. | Approved |
| CC-6 | Payments: own book of record for now, QuickBooks sync later, `accounting_sync_ref` reserved. (Assumed by Claude from the Elektrica answer; Jed to correct if different.) | Assumed — confirm |
| CC-7 | Multi-platform auto-posting is Phase 2+, starts as "generate + queue for one-click human post," becomes true one-button only per platform as each proves stable. | Approved |

---

## 1. What exists today (Kay 007 — facts, not assumptions)

### 1.1 Data store — split, and fragile
Not one Sheet. State is split across `CC_TRACKER_ID` (`1fXk67i4kg-Z8RW5obmXvlWzl_71YSQlgk6-uSuSRZ-E`; tabs `Completed`, `Parts Ordered`, `CC Calendar`, `CC Operations`, `CC Cristian`) **and eight local JSON files on the mini's disk**:

| File | Size | Holds |
|---|---|---|
| `cc_local_data.json` | 174 KB | **Primary job records** incl. protected `_payments`, `_collected`, `_costs` |
| `cc_payment_audit.json` | 54 KB | Payment audit trail |
| `cc_payment_tracking.json` | 21 KB | Payment tracking |
| `cc_gallery.json` | 15 KB | Website gallery posts |
| `cc_part_returns.json`, `cc_cash.json`, `cc_tasks.json`, `cc_tax_payments.json` | small/empty | Parts returns, cash, tasks, (empty) |
| `content_manifest.json` | 141 KB | **Content library index** |

`cc_local_data.json` is the real book of record and was **wiped twice by a race condition on 2026-07-05** (111 jobs → 7). A mutex (`_cc_local_lock`, `_cc_local_update()`) was added. **Whether these files are covered by `backup_daily.py` is unverified.** See §6 action 1.

### 1.2 CCC ONE
- No API, SDK, client, or polling script anywhere in the repo. Verified.
- **Inbound webhook exists:** `/api/cc/cccone-webhook` (`server.py:13264`), logs to `cccone_logs/`, has fired 4 times. **Unauthenticated** (allowlist line 523).
- `dv_engine.py` parses **exported CCC ONE estimate text** (label/value on separate lines). That parser is a reusable asset for Phase 3.

### 1.3 Content library — exists, richer than described
`content_library_routes.py` (22 KB), Drive folder `Content Library`, manifest with 22 fields per upload:
`business, collection, description, drive_id, filename, id, mime, proxy_url, ro_number, service, size, smr, source, stage, status, thumbnail, type, uploaded_at, uploader, url, video_type, web_view_link`.
Uploader, type, and RO number are all present as fields. **Fill rates PENDING AUTH.** Routes `/content-library` and `/api/content/` are **unauthenticated**.

### 1.4 Content generation and posting — built, partly broken
- Caption generator: `/api/cc/marketing/generate`, OpenAI GPT-4o, 5 rotating styles. **Broken**: `OPENAI_API_KEY` unset in the running process (incident CC-1148) while a literal copy is hardcoded in source.
- Posting: `/api/cc/marketing/post` async job + poll (to dodge Cloudflare's 30 s limit), plate-blur step, then Facebook (17 refs, page token), Instagram (same app), Google Business (OAuth), website gallery (`cc_gallery.json`). **TikTok** configured, unverified. **X** one reference, likely unwired.
- Video: Creatomate render with webhook back to `kay.elektricarentals.com`.

### 1.5 Shared process
CC and Elektrica run in **one Flask process, one auth layer**. This is the monolith ADR-001 replaces; it is not a new finding but it means a CC change today can still take down rentals.

---

## 2. Repair-and-collections tracker (Phase 1)

### 2.1 Flow
Customer signs JotForm → imported as a job (RO) → estimate written in CCC ONE and **hand-ported** into the dashboard → repair pipeline → delivered → collections → closed → marketing handoff.

### 2.2 State machine
```
undecided → came_in → estimate → teardown → waiting_on_parts → bodywork
→ paint → detail → delivered → closed_out → marketing
```
- `marketing` is the **hinge state**: it hands the job to the content engine (§3) and is the trigger for before/after generation.
- Every transition is a `case_event` (append-only, same engine as VLS/Elektrica).
- Aging: jobs stalled in `waiting_on_parts` or `estimate` surface themselves; carriers marked "fighting" surface on a collections view.

### 2.3 Entities (proposed — validate against `cc_local_data.json` keys before migrating)
- **`customer`** → `platform.person` via `collision.customer`, RLS per ADR-002.
- **`job`** — RO number, vehicle (VIN/plate), customer, carrier, adjuster, claim number, dates, status, `ccc_one_last_reconciled_at`.
- **`estimate`** — versions; `source` (manual | ccc_one_webhook | ai_proposed), `confirmed_by`, `confirmed_at`; stores AI draft and confirmed final separately (CC-4). Phase 1 stores manual estimates only, but the shape exists from day one because Phase 3 trains on it.
- **`adjuster`** and **`insurance_carrier`** — shared with Elektrica (§1.4 of the Elektrica handoff), extended with a `posture` per job (paying | fighting).
- **`payment`** — shared shape (Elektrica §1.6); migrate `cc_payment_audit.json` and `cc_payment_tracking.json` with provenance.
- **`part_return`**, **`cash_txn`** — from the small JSON files.
- **`communication`** — shared timeline; Phase 2 populates it from the email bot.

### 2.4 CCC ONE re-entry — design for the no-API reality
- A "CCC ONE view" of a job: fields in CCC ONE's entry order, copy-down-the-list.
- `ccc_one_last_reconciled_at` timestamp per job, shown on the job card.
- Inbound webhook payloads land as **proposals** on the matching job (by RO/claim), never applied directly. Requires authenticating the webhook first (§6).

### 2.5 Migration of the JSON stores
Same §2.9 discipline as the Elektrica payment history: export raw → inspect real keys → design to fit → normalise → provenance (`source = cc_local_json`, file, key path) → **verify by aggregate** (job count, total collected, total owed, per-carrier totals old vs new) → freeze the imported audit rows. Run under `_cc_local_lock`; never write back to the JSON.

---

## 3. Content engine

### 3.1 Library (Phase 1 — migrate, don't build)
- Migrate `content_manifest.json` to a `content_item` table keeping all 22 fields; add derived tags (vehicle, stage, colour) AI-assisted, human-editable.
- Views Jed asked for: **by RO** (all media for a job), **by uploader per day** (what did each person work on), **by uploader over time** (who produces the best content — needs an outcome signal; use post engagement from Phase 2 when available, manual rating until then).
- Search across tags/description; the library is only an asset if "red sedan, paint booth, last month" is findable.

### 3.2 Per-job before/after and generation (Phase 2)
- On `marketing` state: pull `content_item`s for the RO, select before/after, generate caption via the existing generator (once the key is restored), plate-blur, **queue for human one-click post** (CC-7).
- Every generated post and every send logged (channel, timestamp, platform response) — same `outbound_log` shape as Elektrica demands.

### 3.3 Platforms (Phase 2, per-platform promotion)
Facebook/Instagram/Google Business are working today and can be true one-button once auth is per-user and logged. Website gallery is trivial. TikTok and X are unverified/unwired: treat as "generate + copy" until each is proven, then promote individually. Do not let either block the tracker.

### 3.4 Video
Creatomate stays as the render service; move its webhook target off the Elektrica domain to the CC service's own endpoint when CC is deployed separately.

---

## 4. Bots (Phase 2)

### 4.1 Email / adjuster bot
Reads shop mailbox → extracts adjuster name/contact, claim number, carrier → attaches to the job **as a proposal** by RO/claim/plate. Same inbound-matching primitive as Elektrica §2.6; third business to need it, so it is confirmed shared.
Outbound status requests: templated "any update on claim X", human-sent or human-approved batch, each logged (CC-5).

### 4.2 Interface contract
Bots write only via scoped API key to proposal endpoints (`POST /api/collision/jobs/{ro}/proposals`), with `source_system`, `observed_at`, `evidence` (message id). No allowlist bypass. Identical to Elektrica §1.7.

---

## 5. Scanner + AI estimator (Phase 3 — horizon, not build)

**What Jed wants:** vehicle drives through a photo scanner → detailed images arrive by email/app → AI writes the estimate → estimators review behind it → bots learn to estimate the way this shop estimates.

**Why it is last:**
1. **Training data does not exist yet.** The estimator learns from this shop's *corrected* estimates. Phase 1's `estimate` table (AI draft vs confirmed) is what accumulates it. No tracker history, no trainable estimator.
2. **No outbound path into CCC ONE.** UI automation against the shop's core system is the most brittle build possible. Phase 3 produces estimate *content* (operations, parts, hours) in CCC ONE entry order for fast human entry. Writing into CCC ONE is a separate, later, fenced project if ever.
3. **An estimate is a financial document.** The review must show what the AI assumed and changed, not a finished number to wave through.

**Reusable now:** `dv_engine.py`'s CCC ONE export parser; the inbound webhook (once authenticated); the `estimate` versioning shape.

**Prerequisite to even scope it:** ~months of confirmed estimates in the new tracker, the scanner vendor's actual output format, and a decision on whether the images route through the email bot or a direct upload.

---

## 6. Actions before any Collision build (in order)

1. **Confirm backups cover the JSON stores.** Kay: does `backup_daily.py` include `cc_local_data.json`, `cc_payment_audit.json`, `content_manifest.json` and the rest? If not, copy them off the mini today. This is the most fragile data in all four businesses.
2. **Extend the auth patch** by three paths: `/api/cc/cccone-webhook` (+ subpath variant), `/content-library`, `/api/content/`. The patch is still unapplied.
3. **Rotate the OpenAI key**, set it in the environment, remove the literal from source. Restores caption generation.
4. **Restore Google OAuth** on the cloud host (58-byte client file) — unblocks every PENDING AUTH item here and in the Elektrica map.
5. Then: JSON export for §2.5, and the `Completed` tab headers.

---

## 7. Open questions (Jed)

1. Payments: own book of record for now, QuickBooks later — correct? (CC-6)
2. Who in the shop uses the dashboard today — just Jed, or estimators/techs too? Affects roles and the uploader identity model.
3. Is the CCC ONE webhook something CCC ONE fires natively, or something Jed configured? What do the 4 logged payloads represent?
4. The scanner: vendor chosen? Output arrives as email attachments, an app, or an API?
5. "Who makes the best content" — measured by post engagement, or by Jed's judgment? Determines whether Phase 2 needs engagement pull-back from platforms.
6. Are the `CC Cristian` and `CC Operations` tabs still live, or legacy?

---

*End of handoff.*

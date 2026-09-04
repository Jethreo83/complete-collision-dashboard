-- 002_collision_job.sql
--
-- Complete Collision RO tracker spine: collision.vehicle, collision.job,
-- collision.job_event.
--
-- Per ADR-001-complete-collision.md §5 (build order item 5) and
-- COMPLETE_COLLISION_HANDOFF_2026-09-03.md §2.1-2.3: "customer signs
-- JotForm -> imported as a job (RO) -> estimate written in CCC ONE and
-- hand-ported into the dashboard -> repair pipeline -> delivered ->
-- collections -> closed -> marketing handoff." State machine (handoff
-- §2.2, decision CC-2, Approved):
--   undecided -> came_in -> estimate -> teardown -> waiting_on_parts ->
--   bodywork -> paint -> detail -> delivered -> closed_out -> marketing
--
-- job.category enum (collision/pdr/hail) matches ROCategory in
-- pdr_settlement.py and the PDR Crew Operating Agreement's three RO
-- categories (ADR-001 §1, §7) -- same three values, kept in sync
-- deliberately.
--
-- Does NOT touch CCC ONE data aggregation (ADR-001 §5 build order item 5
-- explicitly calls this out as safe): every field here is either
-- Complete Collision's own job/payment record, or a
-- ccc_one_last_reconciled_at timestamp used only to show staleness on a
-- job card (handoff §2.4) -- never a copy of CCC ONE's estimate content.
--
-- SIMPLIFICATION, noted rather than hidden: the handoff says job
-- transitions use "the same [case_event] engine as VLS/Elektrica" for
-- state-machine enforcement (e.g. VLS's valid_next_states() trigger
-- pattern). This bot has not read VLS's migration SQL to copy that
-- exact mechanism -- Elektrica's own dashboard hasn't built its
-- analogous spine table yet either (elektrica.rental is still "not yet
-- built" per elektrica-dashboard/README.md), so there is no already-
-- promoted sibling pattern to mirror here beyond what's in this bot's
-- own docs. collision.job_event below is a plain append-only transition
-- log (append, don't overwrite) WITHOUT a SQL-level valid-transition
-- constraint. If Jed wants the exact VLS valid_next_states() enforcement
-- ported over, that requires either his providing the pattern or
-- explicit permission for this bot to read VLS migration source
-- (currently out of scope per this bot's standing VLS boundary).

-- ---------------------------------------------------------------------------
-- collision.vehicle — one row per physical vehicle. A vehicle may belong
-- to multiple jobs over time (repeat customer), so this is not 1:1 with
-- job.
-- ---------------------------------------------------------------------------

CREATE TABLE collision.vehicle (
  id                BIGSERIAL PRIMARY KEY,
  vin               TEXT UNIQUE,  -- nullable: intake may not always have VIN captured yet
  make              TEXT,
  model             TEXT,
  year              INTEGER,
  customer_id       BIGINT NOT NULL REFERENCES collision.customer (id),

  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        TEXT NOT NULL
);

CREATE INDEX idx_vehicle_customer ON collision.vehicle (customer_id);

-- ---------------------------------------------------------------------------
-- collision.job_category / collision.job_status — enums per handoff §2.2
-- (state machine) and the PDR Crew Operating Agreement's RO categories
-- (ADR-001 §1, §7). Both confirmed/approved in source documents, not
-- placeholder guesses.
-- ---------------------------------------------------------------------------

CREATE TYPE collision.job_category AS ENUM (
  'collision',
  'pdr',
  'hail'
);

CREATE TYPE collision.job_status AS ENUM (
  'undecided',
  'came_in',
  'estimate',
  'teardown',
  'waiting_on_parts',
  'bodywork',
  'paint',
  'detail',
  'delivered',
  'closed_out',
  'marketing'
);

-- ---------------------------------------------------------------------------
-- collision.job — the RO tracker spine (handoff §2.3). Cost fields here
-- feed pdr_settlement.py's RepairOrder dataclass directly (same field
-- names by design: gross_revenue, direct_ro_costs, labor_cost,
-- rent_utility_share).
-- ---------------------------------------------------------------------------

CREATE TABLE collision.job (
  id                BIGSERIAL PRIMARY KEY,
  ro_number         TEXT NOT NULL UNIQUE,

  vehicle_id        BIGINT NOT NULL REFERENCES collision.vehicle (id),
  customer_id       BIGINT NOT NULL REFERENCES collision.customer (id),

  site              TEXT NOT NULL,  -- "South" etc. per ADR-001 §4 Site entity;
                                     -- kept as free text here (no multi-site
                                     -- lookup table yet -- Complete Collision
                                     -- currently operates one site plus the
                                     -- co-branded PDR Crew arrangement at the
                                     -- same site, per ADR-001 §1).
  category          collision.job_category NOT NULL,
  status            collision.job_status NOT NULL DEFAULT 'undecided',

  claim_number      TEXT,
  insurer           TEXT,
  adjuster_name     TEXT,
  posture           TEXT,  -- 'paying' | 'fighting', per handoff §2.3 -- kept as
                            -- free text (not enum) since this is a working
                            -- label Jed's staff assigns, not a fixed set
                            -- confirmed from a source document.

  -- Feeds pdr_settlement.py's RepairOrder — see module docstring there.
  -- Manually entered per ADR-001 Phase 1 (no CCC ONE automated read).
  gross_revenue        NUMERIC(12,2) NOT NULL DEFAULT 0,
  direct_ro_costs      NUMERIC(12,2) NOT NULL DEFAULT 0,
  labor_cost           NUMERIC(12,2) NOT NULL DEFAULT 0,
  rent_utility_share   NUMERIC(12,2) NOT NULL DEFAULT 0,

  -- Staleness indicator only (handoff §2.4) — never a copy of CCC ONE's
  -- estimate content, just "when did a human last cross-check this job
  -- against CCC ONE."
  ccc_one_last_reconciled_at TIMESTAMPTZ,

  opened_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at         TIMESTAMPTZ,
  collected_at      TIMESTAMPTZ,

  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        TEXT NOT NULL,
  updated_by        TEXT NOT NULL
);

CREATE INDEX idx_job_customer ON collision.job (customer_id);
CREATE INDEX idx_job_vehicle ON collision.job (vehicle_id);
CREATE INDEX idx_job_status ON collision.job (status);
CREATE INDEX idx_job_category ON collision.job (category);
CREATE INDEX idx_job_site ON collision.job (site);

-- ---------------------------------------------------------------------------
-- collision.job_event — append-only status-transition log. See
-- SIMPLIFICATION note at top of file: no SQL-level valid-transition
-- enforcement yet, application layer is responsible for only writing
-- legal transitions per the handoff §2.2 sequence until/unless the VLS
-- valid_next_states() pattern is ported over with permission.
-- ---------------------------------------------------------------------------

CREATE TABLE collision.job_event (
  id                BIGSERIAL PRIMARY KEY,
  job_id            BIGINT NOT NULL REFERENCES collision.job (id),
  from_status       collision.job_status,  -- NULL for the job's first event (creation)
  to_status         collision.job_status NOT NULL,
  occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        TEXT NOT NULL,
  note              TEXT
);

CREATE INDEX idx_job_event_job ON collision.job_event (job_id, occurred_at);

-- No UPDATE/DELETE grants on job_event below — append-only is enforced by
-- grant shape (INSERT + SELECT only), not a trigger, matching the
-- "append-only" requirement without needing a new mechanism.

-- ---------------------------------------------------------------------------
-- Grants — collision_app already exists (migration 001). Extend to the
-- new tables explicitly (ALL TABLES IN SCHEMA grants from migration 001
-- are a snapshot at GRANT time in Postgres, not dynamic — same note as
-- elektrica migration 002).
-- ---------------------------------------------------------------------------

GRANT SELECT, INSERT, UPDATE ON collision.vehicle TO collision_app;
GRANT SELECT, INSERT, UPDATE ON collision.job TO collision_app;
GRANT SELECT, INSERT ON collision.job_event TO collision_app;  -- no UPDATE/DELETE: append-only
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA collision TO collision_app;

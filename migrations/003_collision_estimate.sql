-- 003_collision_estimate.sql
--
-- collision.estimate — per handoff §2.3: "versions; source (manual |
-- ccc_one_webhook | ai_proposed), confirmed_by, confirmed_at; stores AI
-- draft and confirmed final separately (CC-4)."
--
-- CC-4 (Approved): "AI estimating is propose-and-confirm: the AI produces
-- estimate content laid out for fast entry; a human estimator reviews
-- with the AI's assumptions visible; both the AI draft and the confirmed
-- estimate are stored." Hence draft_content and confirmed_content are
-- separate JSONB columns, never overwritten into each other — a human
-- confirming an estimate writes a NEW value into confirmed_content, the
-- original draft_content stays exactly as proposed for later audit /
-- Phase 3 training-signal purposes (what did the AI get right vs. what
-- did a human change).
--
-- PHASE 1 SCOPE, per handoff §2.3 and ADR-001 §1: "Phase 1 stores manual
-- estimates only, but the shape exists from day one because Phase 3
-- trains on it." This migration creates the full three-value source
-- enum (manual/ccc_one_webhook/ai_proposed) so the shape is right, but:
--   - No code in this repo writes ccc_one_webhook-sourced rows yet. The
--     inbound webhook (/api/cc/cccone-webhook) is unauthenticated and its
--     4 logged payloads have not been inspected yet (ADR-001 §2,
--     currently blocked on kay-successor's access to "the mini" —
--     tracked in WORKLOG.md, not yet resolved as of this migration).
--     Wiring the webhook to actually INSERT collision.estimate rows is
--     explicitly OUT OF SCOPE until that payload inspection and
--     authentication both happen (ADR-001 §2, §5 build order item 2).
--   - No code in this repo writes ai_proposed-sourced rows yet — that is
--     Phase 3 (UVEYE scanner + AI estimator), itself blocked on the CCC
--     ONE license question (ADR-001 §1) and on months of confirmed
--     manual-estimate data existing first (handoff §5). This migration
--     only reserves the shape.
-- Building the shape now, without wiring either non-manual source, is
-- exactly what handoff §2.3 asks for and does not touch CCC ONE data
-- aggregation in any way (no data flows in from CCC ONE via this
-- migration — collision_app can only be given data by this dashboard's
-- own users until the webhook item above is separately resolved).

CREATE TYPE collision.estimate_source AS ENUM (
  'manual',
  'ccc_one_webhook',
  'ai_proposed'
);

CREATE TABLE collision.estimate (
  id                BIGSERIAL PRIMARY KEY,
  job_id            BIGINT NOT NULL REFERENCES collision.job (id),

  -- Versions: multiple estimate rows per job over time (re-estimate after
  -- teardown reveals more damage, etc.) — handoff §2.3 "versions".
  version           INTEGER NOT NULL,

  source            collision.estimate_source NOT NULL,

  -- The proposed content, as first entered/received — immutable after
  -- insert (no UPDATE grant on this table at all, see bottom of file).
  -- For source='manual' in Phase 1, this is simply what the human typed,
  -- confirmed at the same instant (see CHECK constraints below).
  draft_content     JSONB NOT NULL,

  -- The human-confirmed final, set together with draft_content at INSERT
  -- time — never written via a later UPDATE (no UPDATE grant exists on
  -- this table). For source='manual' (the only source Phase 1 writes),
  -- confirmed_content is always set immediately (a human typed the final
  -- content directly). OPEN DESIGN QUESTION for Phase 2/3, not resolved
  -- by this migration: when ai_proposed/ccc_one_webhook sources are
  -- eventually wired, a human "confirming" an AI/webhook draft will need
  -- to happen without ever UPDATE-ing the original proposal row (to keep
  -- draft_content genuinely immutable as the AI-training signal CC-4
  -- wants) — most likely a human confirmation inserts a NEW estimate row
  -- (source='manual', version+1) referencing the AI's version rather than
  -- mutating it in place, but that flow isn't designed or built yet.
  confirmed_content JSONB,
  confirmed_by      TEXT,
  confirmed_at      TIMESTAMPTZ,

  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        TEXT NOT NULL,

  CONSTRAINT estimate_job_version_unique UNIQUE (job_id, version),

  -- Manual estimates are confirmed at creation (a human typed the final
  -- content directly, per Phase 1 scope) — enforce that confirmed_content/
  -- confirmed_by/confirmed_at are all present together, for ANY source,
  -- never partially set. Non-manual sources may legitimately have all
  -- three NULL (still awaiting human review) or all three set (reviewed).
  CONSTRAINT estimate_confirmation_all_or_nothing CHECK (
    (confirmed_content IS NULL AND confirmed_by IS NULL AND confirmed_at IS NULL)
    OR
    (confirmed_content IS NOT NULL AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
  ),

  -- Phase 1 scope enforcement at the schema level, not just in comments:
  -- manual estimates must be confirmed at insert (no unconfirmed-manual
  -- limbo state, since there's no human-review step between a person
  -- typing an estimate and it being "confirmed" for source='manual').
  CONSTRAINT estimate_manual_confirmed_at_creation CHECK (
    source != 'manual' OR confirmed_content IS NOT NULL
  )
);

CREATE INDEX idx_estimate_job ON collision.estimate (job_id, version);
CREATE INDEX idx_estimate_source ON collision.estimate (source);

-- No UPDATE grant, deliberately: handoff §2.3 calls these "versions" —
-- the correction mechanism for an estimate is inserting a new row with
-- version+1, not mutating an existing row in place. This keeps
-- draft_content immutable as the actual historical record of what was
-- proposed, which is exactly what CC-4's "both the AI draft and the
-- confirmed estimate are stored" is protecting: a later correction can't
-- quietly rewrite what the AI (or a person) originally proposed.
GRANT SELECT, INSERT ON collision.estimate TO collision_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA collision TO collision_app;

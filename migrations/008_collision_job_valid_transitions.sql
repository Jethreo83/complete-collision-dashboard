-- 008_collision_job_valid_transitions.sql
--
-- DB-level state-machine enforcement for collision.job.status, closing
-- the gap explicitly flagged in migrations/002's SIMPLIFICATION note:
-- "job transitions use the same case_event engine as VLS/Elektrica"
-- (implying a VLS-style valid_next_states() trigger) — this bot has not
-- read VLS's actual migration SQL (standing VLS boundary), and
-- Elektrica's own analogous table wasn't built at the time either, so
-- collision.job_event was left append-only by grant shape only, with NO
-- SQL-level guarantee that a transition is legal.
--
-- This migration closes that gap using a mechanism this bot DOES have
-- full visibility into: app/models.py's JOB_STATUS_SEQUENCE (already
-- written, tested in test_models.py's validate_transition() tests,
-- and confirmed correct against handoff §2.2's exact sequence). The DB
-- trigger below enforces the SAME rule as the Python function — forward
-- transitions only, skip-ahead allowed, backward and no-op transitions
-- rejected — as a BEFORE UPDATE trigger on collision.job, so an illegal
-- transition is rejected even if some future caller bypasses the Python
-- app layer entirely (a script, a different service, a human running
-- raw SQL).
--
-- This is NOT presented as "the VLS valid_next_states() pattern" copied
-- from real VLS source — it is this bot's own trigger, independently
-- designed from the handoff's plain-English state sequence and the
-- already-existing, already-tested Python reference implementation.
-- Naming it something else (collision.job_status_forward_only) rather
-- than valid_next_states() to avoid implying it's a copy of a pattern
-- this bot has never actually read.
--
-- Enforces the SAME ordering already encoded in
-- app/models.py:JOB_STATUS_SEQUENCE — if that Python list is ever
-- reordered, this migration's array literal must be updated to match,
-- or the two layers will silently disagree about what's legal. Flagging
-- this coupling explicitly rather than hiding it.

CREATE FUNCTION collision.job_status_rank(p_status collision.job_status)
RETURNS INTEGER
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT array_position(
    ARRAY[
      'undecided', 'came_in', 'estimate', 'teardown', 'waiting_on_parts',
      'bodywork', 'paint', 'detail', 'delivered', 'closed_out', 'marketing'
    ]::collision.job_status[],
    p_status
  );
$$;

CREATE FUNCTION collision.job_status_forward_only()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  old_rank INTEGER;
  new_rank INTEGER;
BEGIN
  IF NEW.status = OLD.status THEN
    RAISE EXCEPTION 'collision.job % : no-op status transition (%->%) is not allowed',
      NEW.ro_number, OLD.status, NEW.status;
  END IF;

  old_rank := collision.job_status_rank(OLD.status);
  new_rank := collision.job_status_rank(NEW.status);

  IF new_rank < old_rank THEN
    RAISE EXCEPTION 'collision.job % : backward status transition (%->%) is not allowed',
      NEW.ro_number, OLD.status, NEW.status;
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_job_status_forward_only
  BEFORE UPDATE OF status ON collision.job
  FOR EACH ROW
  EXECUTE FUNCTION collision.job_status_forward_only();

-- No WHEN clause restricting to "status actually changed" here,
-- deliberately: the function itself explicitly REJECTS a no-op
-- transition (NEW.status = OLD.status) as an error, per the same rule
-- app/models.py's validate_transition() already enforces
-- (test_models.py's test_validate_transition_rejects_noop). A WHEN
-- clause filtering out unchanged values would silently let no-op
-- transitions through instead of rejecting them — the opposite of what
-- this migration is for. `BEFORE UPDATE OF status` alone is still the
-- right scope: it only fires when a statement's SET clause references
-- the status column at all, so an unrelated `UPDATE ... SET updated_at
-- = now()` with no status in its SET list never invokes this function.

GRANT EXECUTE ON FUNCTION collision.job_status_rank(collision.job_status) TO collision_app;
GRANT EXECUTE ON FUNCTION collision.job_status_forward_only() TO collision_app;

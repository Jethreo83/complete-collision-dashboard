// src/pages/NewCustomerPage.tsx — new/returning customer intake.
//
// Closes a real UX gap: NewJobPage.tsx requires a person_id typed in by
// staff, but until now there was no screen that could PRODUCE one for a
// walk-in who doesn't already know their platform.person id. This screen
// wraps POST /customers/intake (app/api.py, backed by
// repo.match_or_create_and_link_customer() ->
// platform.match_or_create_person()) and surfaces its real 3-way outcome:
//
//   - 'attached'  -> exact match on email/phone or last_name+DOB found an
//                    existing person; a collision.customer row now links
//                    to it (or already did). person_id is ready to use.
//   - 'created'   -> no match at all; a brand-new platform.person +
//                    collision.customer row was created. person_id is
//                    ready to use.
//   - 'queued'    -> a close-but-not-exact match was found; nothing was
//                    created. A platform.person_match_queue row exists for
//                    a human to resolve (today: via Elektrica's admin
//                    surface, GET/POST /person-match-queue/... -- see
//                    WORKLOG.md/README.md "Not yet built" section; no
//                    Collision-specific queue UI exists yet). person_id is
//                    NOT usable until that queue item is resolved.
//
// This does not replace the "I already know the person_id" flow on
// NewJobPage -- that field stays free-typed. This page's success state
// gives staff a person_id to copy into it (or, once /jobs/new is updated
// to accept a query param, could pre-fill it directly -- not done here to
// keep this change minimal and reviewable, same posture as every other
// "separate follow-up" note in this codebase).
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type CustomerIntakeResult } from '../api';
import { getActor } from '../auth';

export default function NewCustomerPage() {
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [dob, setDob] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [source, setSource] = useState('walk_in');

  const [result, setResult] = useState<CustomerIntakeResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!firstName.trim() || !lastName.trim()) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.intakeCustomer({
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        actor: getActor(),
        date_of_birth: dob.trim() || undefined,
        email: email.trim() || undefined,
        phone: phone.trim() || undefined,
        source,
      });
      setResult(res);
    } catch (e: any) {
      setError(e.body?.detail ?? e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const reset = () => {
    setFirstName(''); setLastName(''); setDob(''); setEmail(''); setPhone('');
    setSource('walk_in'); setResult(null); setError(null);
  };

  return (
    <div style={{ maxWidth: 560 }}>
      <p style={{ color: 'var(--cc-gray)', fontSize: 13 }}>
        Look up or create a customer by identity (email/phone/name+DOB) —
        the shared cross-business match: an exact match on email, phone, or
        last name + date of birth attaches to an existing person (possibly
        already a customer of the other business under this holding
        company); no exact match but a close one queues for human review
        instead of guessing; no match at all creates a brand-new person.
        This is the same primitive Elektrica's renter intake uses.
      </p>

      {!result && (
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <label style={{ fontSize: 13, flex: 1 }}>First Name *<br />
              <input type="text" className="cc-input" value={firstName} onChange={(e) => setFirstName(e.target.value)} style={{ width: '100%' }} />
            </label>
            <label style={{ fontSize: 13, flex: 1 }}>Last Name *<br />
              <input type="text" className="cc-input" value={lastName} onChange={(e) => setLastName(e.target.value)} style={{ width: '100%' }} />
            </label>
          </div>

          <label style={{ fontSize: 13 }}>Date of Birth<br />
            <input type="date" className="cc-input" value={dob} onChange={(e) => setDob(e.target.value)} style={{ width: 200 }} />
          </label>

          <div style={{ display: 'flex', gap: 8 }}>
            <label style={{ fontSize: 13, flex: 1 }}>Email<br />
              <input type="email" className="cc-input" placeholder="name@example.com" value={email} onChange={(e) => setEmail(e.target.value)} style={{ width: '100%' }} />
            </label>
            <label style={{ fontSize: 13, flex: 1 }}>Phone<br />
              <input type="tel" className="cc-input" placeholder="(512) 555-0100" value={phone} onChange={(e) => setPhone(e.target.value)} style={{ width: '100%' }} />
            </label>
          </div>
          <p style={{ fontSize: 11.5, color: 'var(--cc-gray)', margin: 0 }}>
            Supplying at least one of email, phone, or DOB (with last name)
            lets the match actually find an existing person. Leaving all
            three blank will always create a brand-new person record.
          </p>

          <label style={{ fontSize: 13 }}>Source<br />
            <select className="cc-select" value={source} onChange={(e) => setSource(e.target.value)} style={{ width: 200 }}>
              <option value="walk_in">Walk-in</option>
              <option value="insurance_referral">Insurance referral</option>
              <option value="repeat_customer">Repeat customer</option>
              <option value="online">Online</option>
            </select>
          </label>

          {error && <p style={{ color: 'var(--cc-danger)', fontSize: 13 }}>{error}</p>}
          <button type="submit" className="cc-btn" disabled={submitting || !firstName.trim() || !lastName.trim()} style={{ alignSelf: 'flex-start' }}>
            {submitting ? 'Resolving…' : 'Look Up / Create Customer'}
          </button>
        </form>
      )}

      {result && (
        <div className="cc-card" style={{ marginTop: 4 }}>
          {result.match_status === 'attached' && (
            <>
              <div className="label" style={{ color: 'var(--cc-success)' }}>Matched existing customer</div>
              <p style={{ fontSize: 13 }}>
                Found an existing person (id <strong>{result.person_id}</strong>) —
                may already be a Collision or Elektrica record. Ready to use
                on New Job.
              </p>
            </>
          )}
          {result.match_status === 'created' && (
            <>
              <div className="label" style={{ color: 'var(--cc-success)' }}>New customer created</div>
              <p style={{ fontSize: 13 }}>
                No existing match — created person id <strong>{result.person_id}</strong>. Ready to use on New Job.
              </p>
            </>
          )}
          {result.match_status === 'queued' && (
            <>
              <div className="label" style={{ color: 'var(--cc-danger)' }}>Ambiguous match — queued for review</div>
              <p style={{ fontSize: 13 }}>
                A close-but-not-exact match was found. Nothing was created.
                Queue id <strong>{result.queue_id}</strong> — a human must
                resolve this via the shared person-match-queue admin action
                (today: Elektrica's admin surface) before this customer can
                be attached to a job.
              </p>
            </>
          )}
          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            {result.match_status !== 'queued' && (
              <Link to="/jobs/new" className="cc-btn" style={{ textDecoration: 'none' }}>
                Continue to New Job (person_id {result.person_id})
              </Link>
            )}
            <button type="button" className="cc-btn secondary" onClick={reset}>Look up another</button>
          </div>
        </div>
      )}
    </div>
  );
}

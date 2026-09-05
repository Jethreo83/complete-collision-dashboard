// src/pages/StaffIntakePage.tsx — new-hire onboarding via identity match.
//
// Closes the same class of gap NewCustomerPage.tsx closed for customers:
// StaffAdminPage.tsx's "Provision" form requires a person_id staff must
// already know, with nowhere in the app that could produce one for a
// genuinely brand-new hire. This screen wraps POST /staff/intake
// (app/api.py, backed by repo.match_or_create_and_provision_staff() ->
// platform.match_or_create_person()) and surfaces the same real 3-way
// outcome NewCustomerPage does:
//
//   - 'attached'  -> new hire already exists as a platform.person (e.g.
//                    a Collision customer, or the cross-business case
//                    this bot's memory tracks: an Elektrica renter) --
//                    a collision.staff_user row was provisioned against
//                    that existing person. staff record is ready.
//   - 'created'   -> no match -- brand-new platform.person +
//                    collision.staff_user created. staff record is ready.
//   - 'queued'    -> a close-but-not-exact match was found on the
//                    personal contact info. NO staff_user row was
//                    created. A platform.person_match_queue row exists
//                    for a human to resolve (today: Elektrica's admin
//                    surface) -- afterward, use StaffAdminPage's existing
//                    "Provision" form with the resolved person_id.
//
// IMPORTANT distinction (see app/api.py's StaffIntakeRequest docstring):
// google_email is always the COMPANY address
// (@completecollisions.com) and is written to collision.staff_user
// regardless of outcome. personal_email/personal_phone/date_of_birth are
// the new hire's PERSONAL info, used ONLY for identity matching -- never
// written to staff_user. Passing the company email as personal_email
// would be wrong (it was just created by IT, will never match anything).
//
// Does not replace StaffAdminPage's "Provision" form (still the right
// path once a person_id is already known/confirmed, e.g. resolving a
// 'queued' match from this screen).
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type StaffIntakeResult, type StaffRole } from '../api';
import { getActor } from '../auth';

const ROLE_OPTIONS: StaffRole[] = ['owner', 'manager', 'receptionist'];

export default function StaffIntakePage() {
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [role, setRole] = useState<StaffRole>('receptionist');
  const [googleEmail, setGoogleEmail] = useState('');
  const [dob, setDob] = useState('');
  const [personalEmail, setPersonalEmail] = useState('');
  const [personalPhone, setPersonalPhone] = useState('');

  const [result, setResult] = useState<StaffIntakeResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const valid = firstName.trim() && lastName.trim() && googleEmail.trim().toLowerCase().endsWith('@completecollisions.com');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.intakeStaff({
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        role,
        google_email: googleEmail.trim(),
        actor: getActor(),
        date_of_birth: dob.trim() || undefined,
        personal_email: personalEmail.trim() || undefined,
        personal_phone: personalPhone.trim() || undefined,
      });
      setResult(res);
    } catch (e: any) {
      setError(e.body?.detail ?? e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const reset = () => {
    setFirstName(''); setLastName(''); setRole('receptionist'); setGoogleEmail('');
    setDob(''); setPersonalEmail(''); setPersonalPhone('');
    setResult(null); setError(null);
  };

  return (
    <div style={{ maxWidth: 560 }}>
      <p style={{ color: 'var(--cc-gray)', fontSize: 13 }}>
        Onboard a new hire by identity (personal email/phone/name+DOB) —
        the same shared cross-business match NewCustomerPage uses: an
        exact match attaches to an existing person (possibly already a
        Collision customer or Elektrica renter under this holding
        company); a close-but-not-exact match queues for human review
        instead of guessing; no match creates a brand-new person. The
        company Google email below is always written to staff_user
        regardless of outcome — it is never used for matching.
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

          <div style={{ display: 'flex', gap: 8 }}>
            <label style={{ fontSize: 13, flex: 1 }}>Role<br />
              <select className="cc-select" value={role} onChange={(e) => setRole(e.target.value as StaffRole)} style={{ width: '100%' }}>
                {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 13, flex: 1 }}>Company Google Email *<br />
              <input type="email" className="cc-input" placeholder="name@completecollisions.com" value={googleEmail} onChange={(e) => setGoogleEmail(e.target.value)} style={{ width: '100%' }} />
            </label>
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid var(--cc-border, #ddd)', margin: '4px 0' }} />
          <p style={{ fontSize: 11.5, color: 'var(--cc-gray)', margin: 0 }}>
            Personal contact info below is used ONLY for identity matching
            (never written to the staff record). Leaving all three blank
            will always create a brand-new person.
          </p>

          <label style={{ fontSize: 13 }}>Date of Birth (personal)<br />
            <input type="date" className="cc-input" value={dob} onChange={(e) => setDob(e.target.value)} style={{ width: 200 }} />
          </label>

          <div style={{ display: 'flex', gap: 8 }}>
            <label style={{ fontSize: 13, flex: 1 }}>Personal Email<br />
              <input type="email" className="cc-input" placeholder="name@example.com" value={personalEmail} onChange={(e) => setPersonalEmail(e.target.value)} style={{ width: '100%' }} />
            </label>
            <label style={{ fontSize: 13, flex: 1 }}>Personal Phone<br />
              <input type="tel" className="cc-input" placeholder="(512) 555-0100" value={personalPhone} onChange={(e) => setPersonalPhone(e.target.value)} style={{ width: '100%' }} />
            </label>
          </div>

          {error && <p style={{ color: 'var(--cc-danger)', fontSize: 13 }}>{error}</p>}
          <button type="submit" className="cc-btn" disabled={submitting || !valid} style={{ alignSelf: 'flex-start' }}>
            {submitting ? 'Resolving…' : 'Look Up / Onboard Staff'}
          </button>
          {!valid && googleEmail.trim() && (
            <p style={{ fontSize: 11.5, color: 'var(--cc-danger)', margin: 0 }}>
              Company email must end in @completecollisions.com (migrations/009's CHECK constraint).
            </p>
          )}
        </form>
      )}

      {result && (
        <div className="cc-card" style={{ marginTop: 4 }}>
          {result.match_status === 'attached' && (
            <>
              <div className="label" style={{ color: 'var(--cc-success)' }}>Matched existing person</div>
              <p style={{ fontSize: 13 }}>
                Found an existing person (id <strong>{result.person_id}</strong>) —
                may already be a Collision customer or Elektrica renter.
                Staff record provisioned: <strong>{result.staff?.google_email}</strong>.
              </p>
            </>
          )}
          {result.match_status === 'created' && (
            <>
              <div className="label" style={{ color: 'var(--cc-success)' }}>New staff member onboarded</div>
              <p style={{ fontSize: 13 }}>
                No existing match — created person id <strong>{result.person_id}</strong> and
                staff record <strong>{result.staff?.google_email}</strong>.
              </p>
            </>
          )}
          {result.match_status === 'queued' && (
            <>
              <div className="label" style={{ color: 'var(--cc-danger)' }}>Ambiguous match — queued for review</div>
              <p style={{ fontSize: 13 }}>
                A close-but-not-exact match was found. NO staff record was
                created. Queue id <strong>{result.queue_id}</strong> — a
                human must resolve this via the shared person-match-queue
                admin action (today: Elektrica's admin surface), then use
                the "Provision" form on the Staff page with the resolved
                person_id.
              </p>
            </>
          )}
          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <Link to="/staff" className="cc-btn" style={{ textDecoration: 'none' }}>
              Back to Staff
            </Link>
            <button type="button" className="cc-btn secondary" onClick={reset}>Onboard another</button>
          </div>
        </div>
      )}
    </div>
  );
}

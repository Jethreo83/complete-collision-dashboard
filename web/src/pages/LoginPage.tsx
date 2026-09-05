// src/pages/LoginPage.tsx — staff picker (see auth.tsx for why this is
// not real Google OAuth: no backend auth route exists yet).
import { useState } from 'react';
import { useAuth } from '../auth';

export default function LoginPage() {
  const { staffList, error, login } = useAuth();
  const [email, setEmail] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setSubmitting(true);
    setLocalError(null);
    try {
      await login(email.trim());
    } catch (e: any) {
      setLocalError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ display: 'flex', minHeight: '100vh', alignItems: 'center', justifyContent: 'center', background: 'var(--cc-cream)' }}>
      <div style={{ background: 'var(--cc-white)', padding: 40, borderRadius: 'var(--cc-radius)', boxShadow: 'var(--cc-shadow)', width: 380 }}>
        <h2 style={{ color: 'var(--cc-steel)', marginTop: 0 }}>Complete Collision Dashboard</h2>
        <p style={{ fontSize: 13, color: 'var(--cc-gray)' }}>
          Sign in with your staff email (<code>@completecollisions.com</code>).
          Real Google Sign-In is not wired yet — see the project README for
          why; this picks your existing provisioned staff record so writes
          are attributed correctly.
        </p>
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 16 }}>
          <input
            type="email"
            className="cc-input"
            placeholder="you@completecollisions.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            list="staff-emails"
          />
          <datalist id="staff-emails">
            {staffList?.map((s) => <option key={s.id} value={s.google_email} />)}
          </datalist>
          {(localError || error) && <p style={{ color: 'var(--cc-danger)', fontSize: 13 }}>{localError ?? error}</p>}
          <button type="submit" className="cc-btn" disabled={submitting || !email.trim()}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        {staffList && staffList.length === 0 && (
          <p style={{ fontSize: 12.5, color: 'var(--cc-gray)', marginTop: 12 }}>
            No staff provisioned yet. Ask whoever set up the backend to run
            <code> POST /staff</code> for your account first.
          </p>
        )}
      </div>
    </div>
  );
}

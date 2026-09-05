// src/pages/LoginPage.tsx — hermes, 2026-09-05: real backend auth now
// exists; this is no longer a staff picker (see git history for the
// old version). Sign in via the shell launcher, which redirects here
// with a session token. Mirrors Elektrica's LoginPage pattern.
import { useAuth } from '../auth';

export default function LoginPage() {
  const { error } = useAuth();

  return (
    <div style={{ display: 'flex', minHeight: '100vh', alignItems: 'center', justifyContent: 'center', background: 'var(--cc-cream)' }}>
      <div style={{ background: 'var(--cc-white)', padding: 40, borderRadius: 'var(--cc-radius)', boxShadow: 'var(--cc-shadow)', width: 420, textAlign: 'center' }}>
        <h2 style={{ color: 'var(--cc-steel)', marginTop: 0 }}>Complete Collision Dashboard</h2>
        <p style={{ fontSize: 13, color: 'var(--cc-gray)' }}>
          Sign in via the Complete Collision launcher (shell dashboard),
          which will redirect here with your session.
        </p>
        <p style={{ fontSize: 12, color: 'var(--cc-gray)', marginTop: 12 }}>
          For local dev without the shell running, append{' '}
          <code>?token=&lt;signed session token&gt;</code> to this page's URL.
        </p>
        {error && <p style={{ color: 'var(--cc-danger)', fontSize: 13, marginTop: 16 }}>{error}</p>}
      </div>
    </div>
  );
}

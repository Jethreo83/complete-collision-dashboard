// src/auth.tsx — "who is calling" staff-session context.
//
// hermes, 2026-09-05: rewritten from a staff-picker stopgap (see git
// history for the old version's extensive docstring on why it existed)
// now that app/api.py has real shared-secret SSO auth (require_staff /
// enforce_staff_auth per shell-dashboard's JWT_CONTRACT.md). Mirrors
// Elektrica's auth.tsx pattern: read ?token=... from the URL (the
// shell's Launcher appends this), store it, call GET /me to learn who
// signed in and what role they hold in THIS dashboard's own
// staff_user table.
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { apiFetch, getAuthToken, setAuthToken } from './api';

export interface StaffSession {
  person_id: number;
  google_email: string;
  role: string;
  staff_user_id: number;
}

interface AuthContextValue {
  staff: StaffSession | null;
  loading: boolean;
  error: string | null;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [staff, setStaff] = useState<StaffSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Token from the shell's Launcher redirect takes priority; strip it
    // from the URL immediately so it doesn't linger in browser history.
    const fromUrl = new URLSearchParams(window.location.search).get('token');
    if (fromUrl) {
      setAuthToken(fromUrl);
      const url = new URL(window.location.href);
      url.searchParams.delete('token');
      window.history.replaceState({}, '', url.toString());
    }

    const token = getAuthToken();
    if (!token) {
      setLoading(false);
      return;
    }
    apiFetch<StaffSession>('/me')
      .then((s) => setStaff(s))
      .catch((e: any) => {
        setAuthToken(null);
        setError(e.body?.detail ?? e.message);
      })
      .finally(() => setLoading(false));
  }, []);

  const logout = () => {
    setAuthToken(null);
    setStaff(null);
  };

  return (
    <AuthContext.Provider value={{ staff, loading, error, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

/** Actor string for write-attribution fields (existing app/api.py write
 * routes expect an explicit actor string) — now derived from the real
 * verified session instead of an unauthenticated localStorage pick. */
export function getActor(): string {
  const token = getAuthToken();
  if (!token) return 'unknown_staff';
  try {
    const [, payload] = token.split('.');
    const decoded = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
    return decoded.google_email ?? 'unknown_staff';
  } catch {
    return 'unknown_staff';
  }
}

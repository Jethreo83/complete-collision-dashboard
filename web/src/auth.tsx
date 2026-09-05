// src/auth.tsx — "who is calling" staff-session context.
//
// IMPORTANT, read before assuming this mirrors VLS exactly: app/api.py's
// own module docstring says every route is unauthenticated by design —
// there is no /auth/google (or any auth) route on this backend yet, no
// JWT issuance, no session verification. VLS's auth.tsx pattern (Google
// Sign-In -> backend verifies id_token -> issues JWT) cannot be ported
// as-is because the backend half of that contract does not exist here.
//
// This is a deliberate, flagged simplification, not a guess dressed up
// as the real thing: staff "log in" by picking their own already
// provisioned collision.staff_user row (GET /staff), identified by
// google_email. The picked identity is stored in localStorage and sent
// as the `actor` field on every write call (every write route in
// app/api.py requires an explicit actor string). There is NO password,
// NO token, NO server-side session -- this only prevents accidental
// misattribution during normal use, it is NOT a security boundary. Real
// Google OAuth + JWT verification is a backend gap to close before this
// dashboard is used outside a trusted LAN/local demo -- see the final
// report's "open questions" for this exact item.
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, type StaffUser } from './api';

const STORAGE_KEY = 'cc_dashboard_staff_email';

interface AuthContextValue {
  staff: StaffUser | null;
  staffList: StaffUser[] | null;
  loading: boolean;
  error: string | null;
  login: (googleEmail: string) => Promise<void>;
  logout: () => void;
  refreshStaffList: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [staff, setStaff] = useState<StaffUser | null>(null);
  const [staffList, setStaffList] = useState<StaffUser[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshStaffList = () => {
    api.listStaff().then(setStaffList).catch((e) => setError(e.message));
  };

  useEffect(() => {
    refreshStaffList();
  }, []);

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (!saved) {
      setLoading(false);
      return;
    }
    api.getStaffByEmail(saved)
      .then((s) => setStaff(s))
      .catch(() => localStorage.removeItem(STORAGE_KEY))
      .finally(() => setLoading(false));
  }, []);

  const login = async (googleEmail: string) => {
    setError(null);
    try {
      const s = await api.getStaffByEmail(googleEmail);
      if (!s.active) throw new Error(`${googleEmail} is deactivated — ask an owner/manager to reactivate.`);
      localStorage.setItem(STORAGE_KEY, s.google_email);
      setStaff(s);
    } catch (e: any) {
      setError(e.body?.detail ?? e.message);
      throw e;
    }
  };

  const logout = () => {
    localStorage.removeItem(STORAGE_KEY);
    setStaff(null);
  };

  return (
    <AuthContext.Provider value={{ staff, staffList, loading, error, login, logout, refreshStaffList }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

export function getActor(): string {
  const saved = localStorage.getItem(STORAGE_KEY);
  return saved ?? 'unknown_staff';
}

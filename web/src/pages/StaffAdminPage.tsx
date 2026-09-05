// src/pages/StaffAdminPage.tsx — mirrors VLS's StaffAdminPage.tsx pattern.
//
// Difference from VLS: POST /staff here provisions a staff_user for an
// ALREADY-EXISTING platform.person (person_id required) -- it does NOT
// create a brand-new person, unlike whatever VLS's own provisioning
// route does under the hood (see app/api.py's StaffProvisionRequest
// docstring). Also: all three collision roles (owner/manager/
// receptionist) currently resolve to "full" capability per Jed's
// decision (migrations/007) -- there is no restricted role today, so
// the "last active admin" guard rail VLS has doesn't map 1:1. This page
// keeps a lighter version of it (warn if deactivating the last active
// owner) since owner is the closest analogue to VLS's "admin".
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type StaffUser, type StaffRole } from '../api';
import { useAuth, getActor } from '../auth';

const ROLE_OPTIONS: StaffRole[] = ['owner', 'manager', 'receptionist'];

export default function StaffAdminPage() {
  const { staff, refreshStaffList } = useAuth();
  const [rows, setRows] = useState<StaffUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [newPersonId, setNewPersonId] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [newRole, setNewRole] = useState<StaffRole>('receptionist');
  const [saving, setSaving] = useState(false);

  const load = () => {
    api.listStaff().then(setRows).catch((e) => setError(e.body?.detail ?? e.message));
  };

  useEffect(load, []);

  if (staff?.role !== 'owner' && staff?.role !== 'manager') {
    return <p style={{ color: 'var(--cc-danger)' }}>Owner/manager access required.</p>;
  }

  const handleProvision = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPersonId.trim() || !newEmail.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await api.provisionStaff({
        person_id: Number(newPersonId),
        role: newRole,
        google_email: newEmail.trim(),
        actor: getActor(),
      });
      setNewPersonId('');
      setNewEmail('');
      setNewRole('receptionist');
      load();
      refreshStaffList();
    } catch (e: any) {
      setError(e.body?.detail ?? e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleToggleActive = async (row: StaffUser) => {
    if (row.active && row.role === 'owner') {
      const ok = window.confirm(`Deactivate owner ${row.google_email}? They will lose all dashboard access immediately.`);
      if (!ok) return;
    }
    try {
      await api.setStaffActive(row.google_email, { active: !row.active, actor: getActor() });
      load();
      refreshStaffList();
    } catch (e: any) {
      setError(e.body?.detail ?? e.message);
    }
  };

  if (error) return <p style={{ color: 'var(--cc-danger)' }}>{error}</p>;
  if (!rows) return <p>Loading…</p>;

  const activeOwners = rows.filter((r) => r.role === 'owner' && r.active).length;

  return (
    <div>
      <div className="cc-cards">
        <div className="cc-card"><div className="label">Total Staff</div><div className="value">{rows.length}</div></div>
        <div className="cc-card"><div className="label">Active</div><div className="value ok">{rows.filter((r) => r.active).length}</div></div>
        <div className="cc-card"><div className="label">Owners</div><div className={`value ${activeOwners === 0 ? 'warn' : ''}`}>{activeOwners}</div></div>
      </div>

      {activeOwners === 0 && (
        <p style={{ color: 'var(--cc-danger)', fontSize: 13, marginBottom: 16 }}>
          No active owner remains. Provision or reactivate one before continuing.
        </p>
      )}

      <form onSubmit={handleProvision} style={{ display: 'flex', gap: 8, marginBottom: 24, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label style={{ fontSize: 12 }}>
          Person ID<br />
          <input type="number" className="cc-input" placeholder="existing platform.person id" value={newPersonId} onChange={(e) => setNewPersonId(e.target.value)} style={{ width: 160 }} />
        </label>
        <label style={{ fontSize: 12 }}>
          Google email<br />
          <input type="email" className="cc-input" placeholder="name@completecollisions.com" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} style={{ minWidth: 220 }} />
        </label>
        <label style={{ fontSize: 12 }}>
          Role<br />
          <select className="cc-select" value={newRole} onChange={(e) => setNewRole(e.target.value as StaffRole)}>
            {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <button type="submit" className="cc-btn" disabled={saving || !newPersonId.trim() || !newEmail.trim()}>
          {saving ? 'Saving…' : 'Provision'}
        </button>
      </form>
      <p style={{ fontSize: 11.5, color: 'var(--cc-gray)', marginTop: -16, marginBottom: 20 }}>
        person_id must reference an already-existing platform.person row —
        this cannot create a brand new person. Onboarding a genuinely new
        hire (no known person_id yet)? Use{' '}
        <Link to="/staff/new">Onboard Staff</Link> instead, which resolves
        identity from personal contact info first.
      </p>

      <table className="cc-table">
        <thead>
          <tr>
            <th>Email</th>
            <th>Role</th>
            <th>Person ID</th>
            <th>Status</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.google_email}</td>
              <td style={{ textTransform: 'capitalize' }}>{r.role}</td>
              <td>{r.person_id}</td>
              <td><span className={`cc-badge ${r.active ? 'ok' : 'blocked'}`}>{r.active ? 'Active' : 'Inactive'}</span></td>
              <td>
                <button
                  className="cc-signout"
                  onClick={() => handleToggleActive(r)}
                  disabled={r.google_email === staff?.google_email}
                  title={r.google_email === staff?.google_email ? "Can't deactivate your own account" : undefined}
                >
                  {r.active ? 'Deactivate' : 'Reactivate'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

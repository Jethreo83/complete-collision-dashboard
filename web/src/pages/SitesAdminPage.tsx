// src/pages/SitesAdminPage.tsx — frontend consumer for PATCH
// /sites/{id}/active, which has existed in app/api.py since a prior cron
// cycle but had NO frontend consumer at all (WORKLOG-tracked gap, closed
// this cycle) — same class of gap as StaffIntakePage/NewCustomerPage
// closing their own routes' missing consumers in earlier cycles.
//
// IMPORTANT, mirrors app/api.py's own comment above GET /sites in
// api.py: there is deliberately NO "create site" form here. Sites
// (migrations/006, STAGING ONLY -- not yet promoted to production, see
// README's open questions) are only ever created via
// repo.get_or_create_site()'s find-or-create path, invoked from
// POST /jobs (RO intake) and the CSV importers -- never a raw admin
// insert. Site rows are effectively "grown" as they're first referenced
// by real jobs data, matching ADR-001 §4's stance against guessing at
// data (a human never types a brand-new site name into an admin form
// speculatively; it shows up here only after a job or CSV row actually
// used it). This page is read + soft activate/deactivate ONLY.
import { useEffect, useState } from 'react';
import { api, type Site } from '../api';
import { getActor } from '../auth';

export default function SitesAdminPage() {
  const [rows, setRows] = useState<Site[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [showInactive, setShowInactive] = useState(true);

  const load = () => {
    api.listSites(false).then(setRows).catch((e) => setError(e.body?.detail ?? e.message));
  };

  useEffect(load, []);

  const handleToggleActive = async (row: Site) => {
    if (row.active) {
      const ok = window.confirm(
        `Deactivate site "${row.name}"? Existing jobs keep referencing it, but it will drop out of ` +
        `active-site pickers (new job intake, CSV import site matching) until reactivated.`,
      );
      if (!ok) return;
    }
    setBusyId(row.id);
    setError(null);
    try {
      await api.setSiteActive(row.id, { active: !row.active, actor: getActor() });
      load();
    } catch (e: any) {
      setError(e.body?.detail ?? e.message);
    } finally {
      setBusyId(null);
    }
  };

  if (error) return <p style={{ color: 'var(--cc-danger)' }}>{error}</p>;
  if (!rows) return <p>Loading…</p>;

  const visible = showInactive ? rows : rows.filter((r) => r.active);
  const activeCount = rows.filter((r) => r.active).length;

  return (
    <div>
      <div className="cc-cards">
        <div className="cc-card"><div className="label">Total Sites</div><div className="value">{rows.length}</div></div>
        <div className="cc-card"><div className="label">Active</div><div className="value ok">{activeCount}</div></div>
        <div className="cc-card"><div className="label">Inactive</div><div className="value">{rows.length - activeCount}</div></div>
      </div>

      <p style={{ fontSize: 11.5, color: 'var(--cc-gray)', marginBottom: 16 }}>
        Sites are created automatically the first time a real job or CSV
        row references a new site name — there is no "add site" form
        here by design (ADR-001 §4: no guessed data). This page only lets
        you soft activate/deactivate a site that already exists.
      </p>

      <label style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 14 }}>
        <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
        Show inactive sites
      </label>

      <table className="cc-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Address</th>
            <th>Status</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {visible.map((r) => (
            <tr key={r.id}>
              <td><strong>{r.name}</strong></td>
              <td>{r.address ?? <span style={{ color: 'var(--cc-gray)' }}>—</span>}</td>
              <td><span className={`cc-badge ${r.active ? 'ok' : 'blocked'}`}>{r.active ? 'Active' : 'Inactive'}</span></td>
              <td>
                <button
                  className="cc-signout"
                  onClick={() => handleToggleActive(r)}
                  disabled={busyId === r.id}
                >
                  {busyId === r.id ? 'Saving…' : r.active ? 'Deactivate' : 'Reactivate'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {visible.length === 0 && <p style={{ color: 'var(--cc-gray)', marginTop: 12 }}>No sites match this filter.</p>}
    </div>
  );
}

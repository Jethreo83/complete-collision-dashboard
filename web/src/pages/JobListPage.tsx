import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, fmtMoney, money, type RepairOrder, type Site } from '../api';

const STATUS_LABELS: Record<string, string> = {
  undecided: 'Undecided',
  came_in: 'Came In',
  estimate: 'Estimate',
  teardown: 'Teardown',
  waiting_on_parts: 'Waiting on Parts',
  bodywork: 'Bodywork',
  paint: 'Paint',
  detail: 'Detail',
  delivered: 'Delivered',
  closed_out: 'Closed Out',
  marketing: 'Marketing',
};

export default function JobListPage() {
  const [jobs, setJobs] = useState<RepairOrder[] | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [categoryFilter, setCategoryFilter] = useState('all');

  const load = () => {
    Promise.all([
      api.listJobs({ limit: 200 }),
      api.listSites().catch(() => []),
    ])
      .then(([jobRows, siteRows]) => {
        setJobs(jobRows);
        setSites(siteRows);
      })
      .catch((e) => setError(e.message));
  };

  useEffect(load, []);

  const filtered = useMemo(() => {
    if (!jobs) return [];
    let rows = jobs;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter((j) => j.ro_number.toLowerCase().includes(q) || (j.claim_number ?? '').toLowerCase().includes(q));
    }
    if (statusFilter !== 'all') rows = rows.filter((j) => j.status === statusFilter);
    if (categoryFilter !== 'all') rows = rows.filter((j) => j.category === categoryFilter);
    return rows;
  }, [jobs, search, statusFilter, categoryFilter]);

  const siteName = (siteId: number) => sites.find((s) => s.id === siteId)?.name ?? `Site #${siteId}`;

  if (error) return <p style={{ color: 'var(--cc-danger)' }}>Failed to load jobs: {error}</p>;
  if (!jobs) return <p>Loading jobs…</p>;

  const totalRevenue = jobs.reduce((sum, j) => sum + money(j.gross_revenue), 0);
  const totalProfit = jobs.reduce((sum, j) => sum + money(j.net_profit), 0);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <Link to="/jobs/new" className="cc-btn" style={{ textDecoration: 'none' }}>+ New Job (RO Intake)</Link>
      </div>

      <div className="cc-cards">
        <div className="cc-card"><div className="label">Total Jobs</div><div className="value">{jobs.length}</div></div>
        <div className="cc-card"><div className="label">Showing</div><div className="value">{filtered.length}</div></div>
        <div className="cc-card"><div className="label">Total Gross Revenue</div><div className="value">{fmtMoney(totalRevenue)}</div></div>
        <div className="cc-card"><div className="label">Total Net Profit</div><div className={`value ${totalProfit < 0 ? 'warn' : 'ok'}`}>{fmtMoney(totalProfit)}</div></div>
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          type="text"
          className="cc-input"
          placeholder="Search by RO number or claim #…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ minWidth: 240 }}
        />
        <select className="cc-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">All statuses</option>
          {Object.entries(STATUS_LABELS).map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
        <select className="cc-select" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
          <option value="all">All categories</option>
          <option value="collision">Collision</option>
          <option value="pdr">PDR</option>
          <option value="hail">Hail</option>
        </select>
      </div>

      <table className="cc-table">
        <thead>
          <tr>
            <th>RO Number</th>
            <th>Category</th>
            <th>Status</th>
            <th>Site</th>
            <th>Gross Revenue</th>
            <th>Net Profit</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {filtered.map((j) => (
            <tr key={j.id}>
              <td><strong>{j.ro_number}</strong></td>
              <td><span className="cc-badge category">{j.category}</span></td>
              <td><span className="cc-badge status">{STATUS_LABELS[j.status] ?? j.status}</span></td>
              <td>{siteName(j.site_id)}</td>
              <td>{fmtMoney(j.gross_revenue)}</td>
              <td style={{ color: money(j.net_profit) < 0 ? 'var(--cc-danger)' : 'var(--cc-success)', fontWeight: 700 }}>
                {fmtMoney(j.net_profit)}
              </td>
              <td><Link to={`/jobs/${encodeURIComponent(j.ro_number)}`} className="cc-link">View →</Link></td>
            </tr>
          ))}
        </tbody>
      </table>
      {filtered.length === 0 && <p style={{ color: 'var(--cc-gray)', marginTop: 12 }}>No jobs match these filters.</p>}
    </div>
  );
}

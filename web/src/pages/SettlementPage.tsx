// src/pages/SettlementPage.tsx — PDR Crew monthly settlement DRAFT
// calculator. Wires GET /settlements/pdr-crew (app/settlement.py +
// pdr_settlement.py), which itself is explicitly a draft-and-hold
// computation per ADR-001 §7 / pdr_settlement.py's own module
// docstring: this only COMPUTES and DISPLAYS a draft statement for
// Jed's review. Nothing here sends, emails, or delivers anything to
// PDR Crew -- there is no "finalize"/"send" action anywhere in this
// screen or the backend it calls, by design.
import { useState } from 'react';
import { api, fmtMoney, type MonthlySettlement } from '../api';

export default function SettlementPage() {
  const [siteId, setSiteId] = useState('');
  const [month, setMonth] = useState('');
  const [settlement, setSettlement] = useState<MonthlySettlement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!siteId.trim() || !month.trim()) return;
    setLoading(true);
    setError(null);
    setSettlement(null);
    try {
      const s = await api.getPdrSettlement(Number(siteId), month.trim());
      setSettlement(s);
    } catch (e: any) {
      setError(e.body?.detail ?? e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <p style={{ color: 'var(--cc-gray)', maxWidth: 620, marginBottom: 20 }}>
        Computes a <strong>draft</strong> PDR Crew monthly settlement statement
        from job cost/revenue data already entered in the dashboard. This is a
        read-only preview — nothing here sends or finalizes anything with PDR
        Crew; that is a deliberate decision, not a missing feature (see
        pdr_settlement.py's own module docstring).
      </p>

      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 10, marginBottom: 24, alignItems: 'flex-end' }}>
        <label style={{ fontSize: 13 }}>
          Site ID<br />
          <input type="number" className="cc-input" value={siteId} onChange={(e) => setSiteId(e.target.value)} style={{ width: 120 }} />
        </label>
        <label style={{ fontSize: 13 }}>
          Month (YYYY-MM)<br />
          <input type="text" className="cc-input" placeholder="2026-09" value={month} onChange={(e) => setMonth(e.target.value)} style={{ width: 140 }} />
        </label>
        <button type="submit" className="cc-btn" disabled={loading || !siteId.trim() || !month.trim()}>
          {loading ? 'Computing…' : 'Compute Draft Statement'}
        </button>
      </form>

      {error && <p style={{ color: 'var(--cc-danger)' }}>{error}</p>}

      {settlement && (
        <div>
          <div className="cc-cards">
            <div className="cc-card"><div className="label">Site</div><div className="value">{settlement.site}</div></div>
            <div className="cc-card"><div className="label">Month</div><div className="value">{settlement.month}</div></div>
            <div className="cc-card"><div className="label">Status</div><div className="value">{settlement.status}</div></div>
            <div className="cc-card"><div className="label">Total Owed to PDR</div><div className="value ok">{fmtMoney(settlement.total_owed_to_pdr)}</div></div>
          </div>

          <table className="cc-table" style={{ marginBottom: 20 }}>
            <thead>
              <tr>
                <th>Category</th>
                <th>ROs</th>
                <th>Gross Revenue</th>
                <th>Costs Netted</th>
                <th>Net Profit</th>
                <th>CC Share</th>
                <th>PDR Share</th>
              </tr>
            </thead>
            <tbody>
              {settlement.categories.map((c) => (
                <tr key={c.category}>
                  <td style={{ textTransform: 'capitalize' }}>{c.category}</td>
                  <td>{c.ro_numbers.length ? c.ro_numbers.join(', ') : '—'}</td>
                  <td>{fmtMoney(c.gross_revenue)}</td>
                  <td>{fmtMoney(c.total_costs_netted)}</td>
                  <td>{fmtMoney(c.net_profit)}</td>
                  <td>{fmtMoney(c.cc_share_amount)}</td>
                  <td>{fmtMoney(c.pdr_share_amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 style={{ fontSize: 14, color: 'var(--cc-orange-dark)', textTransform: 'uppercase', letterSpacing: '0.6px' }}>Draft Statement Text</h3>
          <pre className="cc-card" style={{ whiteSpace: 'pre-wrap', fontSize: 13, fontFamily: 'monospace' }}>{settlement.statement_text}</pre>
        </div>
      )}
    </div>
  );
}

import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useAuth, getActor } from '../auth';
import {
  api, fmtMoney, money, JOB_STATUS_SEQUENCE,
  type RepairOrder, type JobEvent, type CostEntry, type CostCategory,
  type Payment, type JobPaymentSummary, type PaymentSource,
} from '../api';

const COST_CATEGORIES: CostCategory[] = ['parts', 'labor', 'paint_materials', 'sublet', 'rental_reimbursement', 'other'];
const PAYMENT_SOURCES: PaymentSource[] = ['manual', 'check', 'insurer_eft', 'authorize_net'];

export default function JobDetailPage() {
  const { staff } = useAuth();
  const { roNumber } = useParams();
  const [job, setJob] = useState<RepairOrder | null>(null);
  const [events, setEvents] = useState<JobEvent[] | null>(null);
  const [costs, setCosts] = useState<CostEntry[] | null>(null);
  const [payments, setPayments] = useState<Payment[] | null>(null);
  const [paymentSummary, setPaymentSummary] = useState<JobPaymentSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [targetStatus, setTargetStatus] = useState('');
  const [transitionNote, setTransitionNote] = useState('');
  const [transitioning, setTransitioning] = useState(false);
  const [transitionError, setTransitionError] = useState<string | null>(null);

  const [costCategory, setCostCategory] = useState<CostCategory>('parts');
  const [costAmount, setCostAmount] = useState('');
  const [costDescription, setCostDescription] = useState('');
  const [addingCost, setAddingCost] = useState(false);
  const [costError, setCostError] = useState<string | null>(null);

  const [paymentSource, setPaymentSource] = useState<PaymentSource>('manual');
  const [paymentAmount, setPaymentAmount] = useState('');
  const [paymentRef, setPaymentRef] = useState('');
  const [addingPayment, setAddingPayment] = useState(false);
  const [paymentError, setPaymentError] = useState<string | null>(null);

  const load = () => {
    if (!roNumber) return;
    Promise.all([
      api.getJob(roNumber),
      api.getJobEvents(roNumber),
      api.getJobCosts(roNumber),
      api.getJobPayments(roNumber).catch(() => []), // payments table is staging-only; tolerate 404/500 if not promoted
      api.getJobPaymentsSummary(roNumber).catch(() => null),
    ])
      .then(([j, e, c, p, ps]) => {
        setJob(j);
        setEvents(e);
        setCosts(c);
        setPayments(p);
        setPaymentSummary(ps);
        const nextIdx = JOB_STATUS_SEQUENCE.indexOf(j.status) + 1;
        setTargetStatus(JOB_STATUS_SEQUENCE[nextIdx] ?? '');
      })
      .catch((e) => setError(e.body?.detail ?? e.message));
  };

  useEffect(load, [roNumber]);

  const handleTransition = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!roNumber || !targetStatus) return;
    setTransitioning(true);
    setTransitionError(null);
    try {
      await api.transitionJob(roNumber, {
        target_status: targetStatus as any,
        actor: getActor(),
        note: transitionNote.trim() || undefined,
      });
      setTransitionNote('');
      load();
    } catch (e: any) {
      setTransitionError(e.body?.detail ?? e.message);
    } finally {
      setTransitioning(false);
    }
  };

  const handleAddCost = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!roNumber || !costAmount.trim()) return;
    setAddingCost(true);
    setCostError(null);
    try {
      await api.addJobCost(roNumber, {
        category: costCategory,
        amount: costAmount.trim(),
        actor: getActor(),
        description: costDescription.trim() || undefined,
      });
      setCostAmount('');
      setCostDescription('');
      load();
    } catch (e: any) {
      setCostError(e.body?.detail ?? e.message);
    } finally {
      setAddingCost(false);
    }
  };

  const handleAddPayment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!roNumber || !paymentAmount.trim()) return;
    setAddingPayment(true);
    setPaymentError(null);
    try {
      await api.addJobPayment(roNumber, {
        source: paymentSource,
        amount: paymentAmount.trim(),
        actor: getActor(),
        external_transaction_id: paymentSource === 'authorize_net' ? paymentRef.trim() : undefined,
        accounting_sync_ref: paymentSource !== 'authorize_net' ? paymentRef.trim() || undefined : undefined,
      });
      setPaymentAmount('');
      setPaymentRef('');
      load();
    } catch (e: any) {
      setPaymentError(e.body?.detail ?? e.message);
    } finally {
      setAddingPayment(false);
    }
  };

  if (error) return <p style={{ color: 'var(--cc-danger)' }}>Failed to load job: {error}</p>;
  if (!job) return <p>Loading…</p>;

  const remainingStatuses = JOB_STATUS_SEQUENCE.slice(JOB_STATUS_SEQUENCE.indexOf(job.status) + 1);
  const totalCosts = (costs ?? []).reduce((sum, c) => sum + money(c.amount), 0);

  return (
    <div>
      <p><Link to="/" className="cc-link">&larr; Back to jobs</Link></p>
      <h2 style={{ fontSize: 20, color: 'var(--cc-steel)', marginTop: 12, marginBottom: 20 }}>
        RO #{job.ro_number} — <span style={{ textTransform: 'capitalize' }}>{job.category}</span>
      </h2>

      <section style={{ marginBottom: 24 }}>
        <SectionHeader>Overview</SectionHeader>
        <div className="cc-card">
          <DetailRow label="Status" value={<span className="cc-badge status">{job.status.replace(/_/g, ' ')}</span>} />
          <DetailRow label="Claim number" value={job.claim_number ?? '—'} />
          <DetailRow label="Insurer" value={job.insurer ?? '—'} />
          <DetailRow label="Adjuster" value={job.adjuster_name ?? '—'} />
          <DetailRow label="Posture" value={job.posture ?? '—'} last />
        </div>
      </section>

      <section style={{ marginBottom: 24 }}>
        <SectionHeader>Financials</SectionHeader>
        <div className="cc-card">
          <DetailRow label="Gross revenue" value={fmtMoney(job.gross_revenue)} />
          <DetailRow label="Direct RO costs" value={fmtMoney(job.direct_ro_costs)} />
          <DetailRow label="Labor cost" value={fmtMoney(job.labor_cost)} />
          <DetailRow label="Rent/utility share" value={fmtMoney(job.rent_utility_share)} />
          <DetailRow
            label="Net profit"
            value={<strong style={{ color: money(job.net_profit) < 0 ? 'var(--cc-danger)' : 'var(--cc-success)', fontSize: 16 }}>{fmtMoney(job.net_profit)}</strong>}
            last
          />
        </div>
      </section>

      {paymentSummary && (
        <section style={{ marginBottom: 24 }}>
          <SectionHeader>Payments Collected</SectionHeader>
          <div className="cc-card">
            <DetailRow label="Total collected" value={fmtMoney(paymentSummary.total_collected)} />
            <DetailRow label="Payment count" value={String(paymentSummary.payment_count)} />
            <DetailRow label="Last payment" value={paymentSummary.last_payment_at ? new Date(paymentSummary.last_payment_at).toLocaleString() : '—'} last />
          </div>
        </section>
      )}

      {payments && payments.length > 0 && (
        <section style={{ marginBottom: 24 }}>
          <SectionHeader>Payment History</SectionHeader>
          <table className="cc-table">
            <thead><tr><th>Source</th><th>Amount</th><th>Received</th><th>Reference</th></tr></thead>
            <tbody>
              {payments.map((p) => (
                <tr key={p.id}>
                  <td style={{ textTransform: 'capitalize' }}>{p.source.replace(/_/g, ' ')}</td>
                  <td>{fmtMoney(p.amount)}</td>
                  <td>{new Date(p.received_at).toLocaleDateString()}</td>
                  <td>{p.external_transaction_id ?? p.accounting_sync_ref ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section style={{ marginBottom: 24 }}>
        <SectionHeader>Record a Payment</SectionHeader>
        <div className="cc-card">
          <form onSubmit={handleAddPayment} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <label style={{ fontSize: 12.5 }}>
              Source<br />
              <select className="cc-select" value={paymentSource} onChange={(e) => setPaymentSource(e.target.value as PaymentSource)}>
                {PAYMENT_SOURCES.map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 12.5 }}>
              Amount ($)<br />
              <input type="number" step="0.01" min="0.01" className="cc-input" value={paymentAmount} onChange={(e) => setPaymentAmount(e.target.value)} style={{ width: 120 }} />
            </label>
            <label style={{ fontSize: 12.5, flex: 1 }}>
              {paymentSource === 'authorize_net' ? 'Transaction ID (required)' : 'Reference (optional)'}<br />
              <input type="text" className="cc-input" value={paymentRef} onChange={(e) => setPaymentRef(e.target.value)} style={{ width: '100%' }} />
            </label>
            <button type="submit" className="cc-btn" disabled={addingPayment || !paymentAmount.trim()}>
              {addingPayment ? 'Recording…' : 'Record Payment'}
            </button>
          </form>
          {paymentError && <p style={{ color: 'var(--cc-danger)', fontSize: 13, marginTop: 8 }}>{paymentError}</p>}
        </div>
      </section>

      <section style={{ marginBottom: 24 }}>
        <SectionHeader>Itemized Cost Entries {costs && `(total ${fmtMoney(totalCosts)})`}</SectionHeader>
        {costs && costs.length > 0 ? (
          <table className="cc-table">
            <thead><tr><th>Category</th><th>Description</th><th>Amount</th><th>Incurred</th><th>Source</th></tr></thead>
            <tbody>
              {costs.map((c) => (
                <tr key={c.id}>
                  <td style={{ textTransform: 'capitalize' }}>{c.category.replace(/_/g, ' ')}</td>
                  <td>{c.description ?? '—'}</td>
                  <td>{fmtMoney(c.amount)}</td>
                  <td>{c.incurred_at ?? '—'}</td>
                  <td>{c.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ color: 'var(--cc-gray)' }}>No cost entries yet.</p>
        )}

        <div className="cc-card" style={{ marginTop: 12 }}>
          <form onSubmit={handleAddCost} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <label style={{ fontSize: 12.5 }}>
              Category<br />
              <select className="cc-select" value={costCategory} onChange={(e) => setCostCategory(e.target.value as CostCategory)}>
                {COST_CATEGORIES.map((c) => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 12.5 }}>
              Amount ($)<br />
              <input type="number" step="0.01" min="0.01" className="cc-input" value={costAmount} onChange={(e) => setCostAmount(e.target.value)} style={{ width: 120 }} />
            </label>
            <label style={{ fontSize: 12.5, flex: 1 }}>
              Description (optional)<br />
              <input type="text" className="cc-input" value={costDescription} onChange={(e) => setCostDescription(e.target.value)} style={{ width: '100%' }} />
            </label>
            <button type="submit" className="cc-btn" disabled={addingCost || !costAmount.trim()}>
              {addingCost ? 'Adding…' : 'Add Cost Entry'}
            </button>
          </form>
          {costError && <p style={{ color: 'var(--cc-danger)', fontSize: 13, marginTop: 8 }}>{costError}</p>}
        </div>
      </section>

      <section style={{ marginBottom: 24 }}>
        <SectionHeader>Status History</SectionHeader>
        {events && events.length > 0 ? (
          <div className="cc-card">
            {events.map((e, i) => (
              <div key={e.id} style={{ padding: '10px 0', borderBottom: i === events.length - 1 ? 'none' : '1px solid var(--cc-gray-light)', fontSize: 13.5 }}>
                <strong style={{ textTransform: 'capitalize' }}>
                  {e.from_status ? `${e.from_status.replace(/_/g, ' ')} → ` : ''}{e.to_status.replace(/_/g, ' ')}
                </strong>
                <span style={{ color: 'var(--cc-gray)' }}> — {e.created_by ?? 'unknown'}{e.note ? `: ${e.note}` : ''}</span>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ color: 'var(--cc-gray)' }}>No status history yet.</p>
        )}
      </section>

      <section>
        <SectionHeader>Advance Job Status</SectionHeader>
        <div className="cc-card">
          {remainingStatuses.length === 0 ? (
            <p style={{ color: 'var(--cc-gray)', fontSize: 13.5 }}>
              This job is at its terminal status (<strong>{job.status.replace(/_/g, ' ')}</strong>) — no further forward transitions exist.
            </p>
          ) : (
            <form onSubmit={handleTransition} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <label style={{ fontSize: 13.5 }}>
                Advance to
                <select className="cc-select" value={targetStatus} onChange={(e) => setTargetStatus(e.target.value)} style={{ width: '100%', marginTop: 4 }}>
                  {remainingStatuses.map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
                </select>
              </label>
              <label style={{ fontSize: 13.5 }}>
                Note <span style={{ color: 'var(--cc-gray)' }}>(optional)</span>
                <textarea className="cc-input" value={transitionNote} onChange={(e) => setTransitionNote(e.target.value)} rows={2} style={{ width: '100%', marginTop: 4, resize: 'vertical' }} />
              </label>
              {transitionError && <p style={{ color: 'var(--cc-danger)', fontSize: 13 }}>{transitionError}</p>}
              <button type="submit" className="cc-btn" disabled={transitioning} style={{ alignSelf: 'flex-start' }}>
                {transitioning ? 'Advancing…' : `Advance to ${targetStatus.replace(/_/g, ' ')}`}
              </button>
              <p style={{ fontSize: 11.5, color: 'var(--cc-gray)' }}>Signed in as {staff?.google_email ?? getActor()}.</p>
            </form>
          )}
        </div>
      </section>
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return <h3 style={{ fontSize: 14, color: 'var(--cc-orange-dark)', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: 10 }}>{children}</h3>;
}

function DetailRow({ label, value, last }: { label: string; value: React.ReactNode; last?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: last ? 'none' : '1px solid var(--cc-gray-light)' }}>
      <span style={{ color: 'var(--cc-gray)', fontSize: 13.5 }}>{label}</span>
      <span style={{ fontSize: 13.5, fontWeight: 600 }}>{value}</span>
    </div>
  );
}

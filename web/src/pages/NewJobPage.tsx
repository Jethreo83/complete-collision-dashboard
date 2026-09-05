// src/pages/NewJobPage.tsx — the RO intake path (POST /jobs).
//
// person_id must reference an ALREADY-EXISTING platform.person row (see
// JobIntakeCreateRequest's docstring in app/api.py) — this dashboard does
// not create brand-new people (no privileged DB connection here). The
// "Look up person" button hits GET /persons/{id} (added this cycle) so
// staff can confirm they typed the right person_id before submitting.
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, type JobCategory, type JobStatus } from '../api';
import { getActor } from '../auth';

export default function NewJobPage() {
  const navigate = useNavigate();
  const [personId, setPersonId] = useState('');
  const [personPreview, setPersonPreview] = useState<string | null>(null);
  const [personError, setPersonError] = useState<string | null>(null);
  const [checkingPerson, setCheckingPerson] = useState(false);

  const [roNumber, setRoNumber] = useState('');
  const [category, setCategory] = useState<JobCategory>('collision');
  const [status, setStatus] = useState<JobStatus>('undecided');
  const [siteName, setSiteName] = useState('');
  const [vin, setVin] = useState('');
  const [make, setMake] = useState('');
  const [model, setModel] = useState('');
  const [year, setYear] = useState('');
  const [claimNumber, setClaimNumber] = useState('');
  const [insurer, setInsurer] = useState('');
  const [grossRevenue, setGrossRevenue] = useState('0');

  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleLookupPerson = async () => {
    if (!personId.trim()) return;
    setCheckingPerson(true);
    setPersonError(null);
    setPersonPreview(null);
    try {
      const p = await api.apiFetchPerson(personId.trim());
      setPersonPreview(`${p.first_name ?? ''} ${p.last_name ?? ''} (${p.email_normalized ?? 'no email on file'})`.trim());
    } catch (e: any) {
      setPersonError(e.body?.detail ?? e.message);
    } finally {
      setCheckingPerson(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!personId.trim() || !roNumber.trim() || !siteName.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const job = await api.createJob({
        person_id: Number(personId),
        customer_source: 'walk_in',
        site_name: siteName.trim(),
        ro_number: roNumber.trim(),
        category,
        status,
        vin: vin.trim() || undefined,
        make: make.trim() || undefined,
        model: model.trim() || undefined,
        year: year.trim() ? Number(year) : undefined,
        claim_number: claimNumber.trim() || undefined,
        insurer: insurer.trim() || undefined,
        gross_revenue: grossRevenue.trim() || '0',
        actor: getActor(),
      });
      navigate(`/jobs/${encodeURIComponent(job.ro_number)}`);
    } catch (e: any) {
      setError(e.body?.detail ?? e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ maxWidth: 560 }}>
      <p style={{ color: 'var(--cc-gray)', fontSize: 13 }}>
        Creates a new RO (repair order) job. <code>person_id</code> must
        already exist in the shared platform person table — this
        dashboard cannot create brand-new people yet (see README/open
        questions).
      </p>
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <label style={{ fontSize: 13, flex: 1 }}>
            Person ID *<br />
            <input type="number" className="cc-input" value={personId} onChange={(e) => { setPersonId(e.target.value); setPersonPreview(null); }} style={{ width: '100%' }} />
          </label>
          <button type="button" className="cc-btn secondary" onClick={handleLookupPerson} disabled={checkingPerson || !personId.trim()}>
            {checkingPerson ? 'Checking…' : 'Look up'}
          </button>
        </div>
        {personPreview && <p style={{ color: 'var(--cc-success)', fontSize: 12.5, margin: 0 }}>✓ {personPreview}</p>}
        {personError && <p style={{ color: 'var(--cc-danger)', fontSize: 12.5, margin: 0 }}>{personError}</p>}

        <label style={{ fontSize: 13 }}>RO Number *<br />
          <input type="text" className="cc-input" value={roNumber} onChange={(e) => setRoNumber(e.target.value)} style={{ width: '100%' }} />
        </label>

        <div style={{ display: 'flex', gap: 10 }}>
          <label style={{ fontSize: 13, flex: 1 }}>Category<br />
            <select className="cc-select" value={category} onChange={(e) => setCategory(e.target.value as JobCategory)} style={{ width: '100%' }}>
              <option value="collision">Collision</option>
              <option value="pdr">PDR</option>
              <option value="hail">Hail</option>
            </select>
          </label>
          <label style={{ fontSize: 13, flex: 1 }}>Initial Status<br />
            <select className="cc-select" value={status} onChange={(e) => setStatus(e.target.value as JobStatus)} style={{ width: '100%' }}>
              <option value="undecided">Undecided</option>
              <option value="came_in">Came In</option>
            </select>
          </label>
        </div>

        <label style={{ fontSize: 13 }}>Site Name *<br />
          <input type="text" className="cc-input" placeholder="e.g. Main Shop" value={siteName} onChange={(e) => setSiteName(e.target.value)} style={{ width: '100%' }} />
        </label>

        <fieldset style={{ border: '1px solid var(--cc-gray-light)', borderRadius: 8, padding: 12 }}>
          <legend style={{ fontSize: 12, color: 'var(--cc-gray)' }}>Vehicle (optional)</legend>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input type="text" className="cc-input" placeholder="VIN" value={vin} onChange={(e) => setVin(e.target.value)} style={{ flex: '1 1 160px' }} />
            <input type="text" className="cc-input" placeholder="Make" value={make} onChange={(e) => setMake(e.target.value)} style={{ flex: '1 1 100px' }} />
            <input type="text" className="cc-input" placeholder="Model" value={model} onChange={(e) => setModel(e.target.value)} style={{ flex: '1 1 100px' }} />
            <input type="number" className="cc-input" placeholder="Year" value={year} onChange={(e) => setYear(e.target.value)} style={{ flex: '1 1 80px' }} />
          </div>
        </fieldset>

        <fieldset style={{ border: '1px solid var(--cc-gray-light)', borderRadius: 8, padding: 12 }}>
          <legend style={{ fontSize: 12, color: 'var(--cc-gray)' }}>Insurance (optional)</legend>
          <div style={{ display: 'flex', gap: 8 }}>
            <input type="text" className="cc-input" placeholder="Claim number" value={claimNumber} onChange={(e) => setClaimNumber(e.target.value)} style={{ flex: 1 }} />
            <input type="text" className="cc-input" placeholder="Insurer" value={insurer} onChange={(e) => setInsurer(e.target.value)} style={{ flex: 1 }} />
          </div>
        </fieldset>

        <label style={{ fontSize: 13 }}>Gross Revenue ($)<br />
          <input type="number" step="0.01" className="cc-input" value={grossRevenue} onChange={(e) => setGrossRevenue(e.target.value)} style={{ width: 160 }} />
        </label>

        {error && <p style={{ color: 'var(--cc-danger)', fontSize: 13 }}>{error}</p>}
        <button type="submit" className="cc-btn" disabled={submitting} style={{ alignSelf: 'flex-start' }}>
          {submitting ? 'Creating…' : 'Create Job'}
        </button>
      </form>
    </div>
  );
}

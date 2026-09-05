// src/pages/JobLookupPage.tsx — direct "look up a job by RO number" screen.
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';

export default function JobLookupPage() {
  const [roNumber, setRoNumber] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!roNumber.trim()) return;
    setSearching(true);
    setError(null);
    try {
      await api.getJob(roNumber.trim());
      navigate(`/jobs/${encodeURIComponent(roNumber.trim())}`);
    } catch (e: any) {
      setError(e.body?.detail ?? e.message);
    } finally {
      setSearching(false);
    }
  };

  return (
    <div>
      <p style={{ color: 'var(--cc-gray)', maxWidth: 480, marginBottom: 20 }}>
        Enter an RO (repair order) number to jump straight to that job's detail page.
      </p>
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 10, maxWidth: 420 }}>
        <input
          type="text"
          className="cc-input"
          placeholder="e.g. RO-2026-0142"
          value={roNumber}
          onChange={(e) => setRoNumber(e.target.value)}
          style={{ flex: 1 }}
          autoFocus
        />
        <button type="submit" className="cc-btn" disabled={searching || !roNumber.trim()}>
          {searching ? 'Looking up…' : 'Look Up'}
        </button>
      </form>
      {error && <p style={{ color: 'var(--cc-danger)', marginTop: 12 }}>{error}</p>}
    </div>
  );
}

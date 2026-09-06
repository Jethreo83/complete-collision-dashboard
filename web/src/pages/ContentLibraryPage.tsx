// src/pages/ContentLibraryPage.tsx — frontend consumer for POST
// /content-items, GET /content-items(?q=...), PATCH /content-items/{id}/tags,
// which have existed in app/api.py since the 2026-09-05 "collision.content_item
// app layer" cycle but had NO frontend consumer at all (WORKLOG-tracked
// gap, closed this cycle) — same class of gap SitesAdminPage/StaffIntakePage
// closed for their own routes in earlier cycles.
//
// Dashboard-native-upload scope only, matching app/api.py's Content
// library section comment: no actual file bytes handled here (no
// multipart, no Drive API) — filename/url/proxy_url/drive_id point at
// wherever the caller already stored the file. A real bulk
// content_manifest.json import (141 KB, per handoff §3.1) remains
// blocked on export access to "the mini"; this screen only supports a
// human typing in metadata for a file they already have stored
// somewhere (e.g. a Drive link), same discipline as every other
// manually-entered field in this codebase.
//
// derived_tags/derived_tags_source are AI-assisted-but-human-editable
// per handoff §3.1 — no AI tagging pipeline exists yet (see
// app.models.ContentItem's docstring), so every tag edit made here is
// recorded with derived_tags_source='human', never silently defaulted.
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type ContentItem } from '../api';
import { getActor } from '../auth';

export default function ContentLibraryPage() {
  const [items, setItems] = useState<ContentItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  const [filename, setFilename] = useState('');
  const [roNumber, setRoNumber] = useState('');
  const [description, setDescription] = useState('');
  const [url, setUrl] = useState('');
  const [type, setType] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingTags, setEditingTags] = useState('');
  const [savingTags, setSavingTags] = useState(false);

  const load = (q?: string) => {
    api.listContentItems({ q: q || undefined, limit: 100 })
      .then(setItems)
      .catch((e) => setError(e.body?.detail ?? e.message));
  };

  useEffect(() => load(), []);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    load(query.trim());
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!filename.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      await api.createContentItem({
        filename: filename.trim(),
        actor: getActor(),
        ro_number: roNumber.trim() || undefined,
        description: description.trim() || undefined,
        url: url.trim() || undefined,
        type: type.trim() || undefined,
      });
      setFilename(''); setRoNumber(''); setDescription(''); setUrl(''); setType('');
      setShowForm(false);
      load(query.trim());
    } catch (e: any) {
      setCreateError(e.body?.detail ?? e.message);
    } finally {
      setCreating(false);
    }
  };

  const startEditTags = (item: ContentItem) => {
    setEditingId(item.id);
    setEditingTags((item.derived_tags ?? []).join(', '));
  };

  const handleSaveTags = async (id: number) => {
    setSavingTags(true);
    try {
      const tags = editingTags.split(',').map((t) => t.trim()).filter(Boolean);
      await api.updateContentItemTags(id, {
        derived_tags: tags,
        derived_tags_source: 'human',
        actor: getActor(),
      });
      setEditingId(null);
      load(query.trim());
    } catch (e: any) {
      setError(e.body?.detail ?? e.message);
    } finally {
      setSavingTags(false);
    }
  };

  if (error) return <p style={{ color: 'var(--cc-danger)' }}>{error}</p>;

  return (
    <div>
      <p style={{ fontSize: 11.5, color: 'var(--cc-gray)', marginBottom: 16, maxWidth: 720 }}>
        Records metadata for photos/video/docs already stored somewhere
        (e.g. a Drive link) — no file bytes are uploaded through this
        screen. A future bulk import of the real content_manifest.json is
        still blocked on export access; this is the dashboard-native path
        only. Tags are AI-assisted but human-editable — every edit made
        here is recorded as a human correction, never silently defaulted.
      </p>

      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <form onSubmit={handleSearch} style={{ display: 'flex', gap: 8, flex: 1 }}>
          <input
            type="text"
            className="cc-input"
            placeholder="Search description or tags…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ flex: 1, minWidth: 220 }}
          />
          <button type="submit" className="cc-btn secondary">Search</button>
        </form>
        <button type="button" className="cc-btn" onClick={() => setShowForm((v) => !v)}>
          {showForm ? 'Cancel' : '+ Add Content Item'}
        </button>
      </div>

      {showForm && (
        <div className="cc-card" style={{ marginBottom: 20 }}>
          <form onSubmit={handleCreate} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <label style={{ fontSize: 12.5 }}>
              Filename *<br />
              <input type="text" className="cc-input" value={filename} onChange={(e) => setFilename(e.target.value)} style={{ width: 180 }} />
            </label>
            <label style={{ fontSize: 12.5 }}>
              RO # (optional)<br />
              <input type="text" className="cc-input" placeholder="e.g. RO-2026-0142" value={roNumber} onChange={(e) => setRoNumber(e.target.value)} style={{ width: 150 }} />
            </label>
            <label style={{ fontSize: 12.5 }}>
              Type (optional)<br />
              <input type="text" className="cc-input" placeholder="photo / video / doc" value={type} onChange={(e) => setType(e.target.value)} style={{ width: 120 }} />
            </label>
            <label style={{ fontSize: 12.5, flex: 1 }}>
              Stored URL (optional)<br />
              <input type="text" className="cc-input" placeholder="Drive link, etc." value={url} onChange={(e) => setUrl(e.target.value)} style={{ width: '100%' }} />
            </label>
            <label style={{ fontSize: 12.5, flex: 1, minWidth: 200 }}>
              Description (optional)<br />
              <input type="text" className="cc-input" value={description} onChange={(e) => setDescription(e.target.value)} style={{ width: '100%' }} />
            </label>
            <button type="submit" className="cc-btn" disabled={creating || !filename.trim()}>
              {creating ? 'Adding…' : 'Add'}
            </button>
          </form>
          {createError && <p style={{ color: 'var(--cc-danger)', fontSize: 13, marginTop: 8 }}>{createError}</p>}
        </div>
      )}

      {!items ? (
        <p>Loading…</p>
      ) : items.length === 0 ? (
        <p style={{ color: 'var(--cc-gray)' }}>No content items match this search.</p>
      ) : (
        <table className="cc-table">
          <thead>
            <tr>
              <th>Filename</th>
              <th>RO #</th>
              <th>Type</th>
              <th>Description</th>
              <th>Tags</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>
                  {item.url ? (
                    <a className="cc-link" href={item.url} target="_blank" rel="noreferrer">{item.filename}</a>
                  ) : (
                    <strong>{item.filename}</strong>
                  )}
                </td>
                <td>
                  {item.ro_number ? (
                    <Link className="cc-link" to={`/jobs/${encodeURIComponent(item.ro_number)}`}>{item.ro_number}</Link>
                  ) : '—'}
                </td>
                <td>{item.type ?? '—'}</td>
                <td>{item.description ?? '—'}</td>
                <td>
                  {editingId === item.id ? (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <input
                        type="text"
                        className="cc-input"
                        value={editingTags}
                        onChange={(e) => setEditingTags(e.target.value)}
                        placeholder="comma, separated, tags"
                        style={{ width: 160 }}
                      />
                      <button type="button" className="cc-btn" disabled={savingTags} onClick={() => handleSaveTags(item.id)}>
                        {savingTags ? '…' : 'Save'}
                      </button>
                      <button type="button" className="cc-btn secondary" onClick={() => setEditingId(null)}>Cancel</button>
                    </div>
                  ) : (
                    <>
                      {(item.derived_tags ?? []).length > 0
                        ? item.derived_tags.map((t) => <span key={t} className="cc-badge category" style={{ marginRight: 4 }}>{t}</span>)
                        : <span style={{ color: 'var(--cc-gray)' }}>—</span>}
                      {' '}
                      <span className={`cc-badge ${item.derived_tags_source === 'ai' ? 'status' : 'ok'}`} style={{ marginLeft: 4 }}>
                        {item.derived_tags_source}
                      </span>
                    </>
                  )}
                </td>
                <td>
                  {editingId !== item.id && (
                    <button type="button" className="cc-signout" onClick={() => startEditTags(item)}>Edit tags</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

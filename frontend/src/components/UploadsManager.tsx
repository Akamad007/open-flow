import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { UploadRef } from '../types';

interface Props {
  projectId: string;
}

/**
 * UploadsManager — shown on the project detail page (or wherever the user
 * needs to attach reference images). Two SEPARATE upload widgets:
 * 1. Character (face / full-body) → flows into InstantID + SD3.5 img2img.
 * 2. Product (hero shot) → flows into per-scene action-still img2img.
 *
 * Each upload requires a free-text label; downstream label-matching links
 * the upload to the LLM-extracted Character / Product entity by shared word.
 */
export function UploadsManager({ projectId }: Props) {
  const [uploads, setUploads] = useState<UploadRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      setUploads(await api.listUploads(projectId));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, [projectId]);

  const characters = uploads.filter(u => u.kind === 'character');
  const products = uploads.filter(u => u.kind === 'product');

  const handleDelete = async (assetId: string) => {
    if (!confirm('Delete this reference image?')) return;
    try {
      await api.deleteUpload(projectId, assetId);
      await refresh();
    } catch (e) {
      alert(String(e));
    }
  };

  if (loading) return <div style={{ padding: 12 }}>Loading uploads…</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {error && (
        <div style={{ color: '#c00', padding: 8, border: '1px solid #c00' }}>{error}</div>
      )}

      <UploadKindSection
        title="Character references"
        helpText="Upload a face or full-body shot of a character in your story. The label must match (case-insensitive, word-overlap) the character name from the story so the pipeline can link it. Used as InstantID identity + SD3.5 img2img init."
        kind="character"
        projectId={projectId}
        items={characters}
        onUploaded={refresh}
        onDelete={handleDelete}
      />

      <UploadKindSection
        title="Product references"
        helpText="Upload a hero shot of a product mentioned in your story (ideally on a plain background). The label must match (case-insensitive, word-overlap) the product name from the story. Used as SD3.5 img2img init for per-scene action stills."
        kind="product"
        projectId={projectId}
        items={products}
        onUploaded={refresh}
        onDelete={handleDelete}
      />
    </div>
  );
}

interface SectionProps {
  title: string;
  helpText: string;
  kind: 'character' | 'product';
  projectId: string;
  items: UploadRef[];
  onUploaded: () => Promise<void>;
  onDelete: (assetId: string) => Promise<void>;
}

function UploadKindSection({ title, helpText, kind, projectId, items, onUploaded, onDelete }: SectionProps) {
  const [label, setLabel] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !label.trim()) {
      setUploadError('Pick a file and provide a label.');
      return;
    }
    setUploading(true);
    setUploadError(null);
    try {
      if (kind === 'character') {
        await api.uploadCharacter(projectId, label.trim(), file);
      } else {
        await api.uploadProduct(projectId, label.trim(), file);
      }
      setLabel('');
      setFile(null);
      const input = document.getElementById(`upload-input-${kind}`) as HTMLInputElement | null;
      if (input) input.value = '';
      await onUploaded();
    } catch (e) {
      setUploadError(String(e));
    } finally {
      setUploading(false);
    }
  };

  return (
    <section style={{ border: '1px solid #ddd', padding: 16, borderRadius: 6 }}>
      <h3 style={{ marginTop: 0 }}>{title}</h3>
      <p style={{ fontSize: 13, color: '#666', marginTop: -4 }}>{helpText}</p>

      <form onSubmit={handleUpload} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 12 }}>
        <input
          type="text"
          placeholder={kind === 'character' ? 'Character name (e.g. "Alice")' : 'Product name (e.g. "tan Birkin handbag")'}
          value={label}
          onChange={e => setLabel(e.target.value)}
          style={{ flex: '1 1 240px', minWidth: 200, padding: 6 }}
          disabled={uploading}
        />
        <input
          id={`upload-input-${kind}`}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          onChange={e => setFile(e.target.files?.[0] || null)}
          disabled={uploading}
        />
        <button type="submit" disabled={uploading || !file || !label.trim()}>
          {uploading ? 'Uploading…' : 'Upload'}
        </button>
      </form>
      {uploadError && <div style={{ color: '#c00', fontSize: 13, marginBottom: 8 }}>{uploadError}</div>}

      {items.length === 0 ? (
        <div style={{ color: '#888', fontSize: 13 }}>No {kind} uploads yet.</div>
      ) : (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
          {items.map(u => (
            <li key={u.asset_id} style={{ border: '1px solid #eee', borderRadius: 4, padding: 8 }}>
              <img
                src={`/storage/${u.file_path.replace(/^storage\//, '')}`}
                alt={u.label}
                style={{ width: '100%', height: 120, objectFit: 'cover', borderRadius: 4, background: '#f5f5f5' }}
              />
              <div style={{ fontSize: 13, marginTop: 6, fontWeight: 500 }}>{u.label}</div>
              <button
                onClick={() => onDelete(u.asset_id)}
                style={{ marginTop: 6, fontSize: 12, color: '#c00', background: 'none', border: '1px solid #c00', borderRadius: 3, padding: '3px 8px', cursor: 'pointer' }}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

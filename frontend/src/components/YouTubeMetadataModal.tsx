import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { EpisodeListItem } from '../types'

interface Props {
  episode: EpisodeListItem
  onClose: () => void
}

export function YouTubeMetadataModal({ episode, onClose }: Props) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState<'title' | 'description' | 'both' | null>(null)
  const triedAuto = useRef(false)

  const generate = async () => {
    setGenerating(true); setError(null)
    try {
      const r = await api.suggestYoutubeMetadata(episode.id)
      setTitle(r.title)
      setDescription(r.description)
    } catch (e: any) {
      setError(`Generate failed: ${e?.message || e}`)
    } finally { setGenerating(false) }
  }

  useEffect(() => {
    if (triedAuto.current) return
    triedAuto.current = true
    generate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const copy = async (text: string, which: typeof copied) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(which)
      window.setTimeout(() => setCopied(null), 1500)
    } catch (e: any) {
      setError(`Copy failed: ${e?.message || e}`)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 720 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h3 style={{ margin: 0 }}>YouTube metadata — Ep {episode.order_index}</h3>
          <button
            type="button" className="btn btn-sm"
            onClick={generate} disabled={generating}
            title="Re-generate title + description with the configured LLM"
          >
            {generating ? '✨ Generating…' : '✨ Regenerate'}
          </button>
        </div>
        <p className="muted" style={{ fontSize: 12, marginTop: 4 }}>
          Paste these into YouTube's web upload UI (we don't upload — only generate).
        </p>

        <div className="form-row">
          <label>
            Title <span className="muted">({title.length}/100)</span>
            <button
              type="button" className="btn btn-sm" style={{ marginLeft: 8 }}
              onClick={() => copy(title, 'title')} disabled={!title || generating}
            >
              {copied === 'title' ? '✓ Copied' : '📋 Copy'}
            </button>
          </label>
          <input
            type="text" value={title} onChange={e => setTitle(e.target.value)}
            placeholder={generating ? 'Generating…' : 'Title'}
          />
        </div>

        <div className="form-row">
          <label>
            Description <span className="muted">({description.length}/5000)</span>
            <button
              type="button" className="btn btn-sm" style={{ marginLeft: 8 }}
              onClick={() => copy(description, 'description')} disabled={!description || generating}
            >
              {copied === 'description' ? '✓ Copied' : '📋 Copy'}
            </button>
          </label>
          <textarea
            rows={14} value={description} onChange={e => setDescription(e.target.value)}
            placeholder={generating ? 'Generating…' : 'Description'}
            style={{ fontFamily: 'inherit' }}
          />
        </div>

        {error && <div className="error">{error}</div>}
        <div className="modal-actions">
          <button
            className="btn"
            onClick={() => copy(`${title}\n\n${description}`, 'both')}
            disabled={!title || !description || generating}
          >
            {copied === 'both' ? '✓ Copied both' : '📋 Copy title + description'}
          </button>
          <button className="btn btn-primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  )
}

import { useState } from 'react'
import { api } from '../api/client'
import type { Scene } from '../types'

interface Props {
  projectId: string
  episodeId: string | null  // target episode; null → backend uses the active one
  onClose: () => void
  onCreated: (scene: Scene) => void
}

export function AddSceneModal({ projectId, episodeId, onClose, onCreated }: Props) {
  const [visualSummary, setVisualSummary] = useState('')
  const [scenePurpose, setScenePurpose] = useState('')
  const [sourceExcerpt, setSourceExcerpt] = useState('')
  const [duration, setDuration] = useState(4)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    setError(null)
    setSubmitting(true)
    try {
      const scene = await api.createScene(projectId, {
        episode_id: episodeId || undefined,
        visual_summary: visualSummary.trim() || undefined,
        scene_purpose: scenePurpose.trim() || undefined,
        source_excerpt: sourceExcerpt.trim() || undefined,
        duration_seconds: duration,
      })
      onCreated(scene)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally { setSubmitting(false) }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h3>Add scene</h3>
        <label className="field">
          <span>Visual summary</span>
          <textarea
            value={visualSummary}
            onChange={e => setVisualSummary(e.target.value)}
            placeholder="What happens on screen in this scene"
            rows={3}
          />
          <small className="muted">Appended to the end of the selected episode. Edit the prompt after creating.</small>
        </label>
        <label className="field">
          <span>Scene purpose <span className="muted">(optional)</span></span>
          <input
            type="text" value={scenePurpose}
            onChange={e => setScenePurpose(e.target.value)}
            placeholder="Why this scene exists in the story"
          />
        </label>
        <label className="field">
          <span>Source excerpt <span className="muted">(optional)</span></span>
          <textarea
            value={sourceExcerpt}
            onChange={e => setSourceExcerpt(e.target.value)}
            placeholder="The line(s) of source story this scene depicts"
            rows={2}
          />
        </label>
        <label className="field">
          <span>Duration (seconds)</span>
          <input
            type="number" min={1} max={30} step={0.5} value={duration}
            onChange={e => setDuration(Number(e.target.value))}
          />
        </label>
        {error && <div className="error">{error}</div>}
        <div className="modal-actions">
          <button className="btn" onClick={onClose} disabled={submitting}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? 'Adding…' : 'Add scene ▶'}
          </button>
        </div>
      </div>
    </div>
  )
}

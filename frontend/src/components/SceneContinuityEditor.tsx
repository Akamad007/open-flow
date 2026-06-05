import { useState, useEffect } from 'react'
import { api } from '../api/client'
import type { Scene } from '../types'

interface Props {
  scene: Scene
  scenes: Scene[]   // all scenes in the episode (to pick a predecessor from)
  onSaved?: () => void
}

/** Edit a scene's continuity: pin which earlier scene it continues from
 *  (overrides the auto character-overlap chain) plus the prose hand-off notes. */
export function SceneContinuityEditor({ scene, scenes, onSaved }: Props) {
  const [prevId, setPrevId] = useState(scene.continuity_prev_scene_id || '')
  const [fromPrev, setFromPrev] = useState(scene.continuity_from_previous || '')
  const [toNext, setToNext] = useState(scene.continuity_to_next || '')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setPrevId(scene.continuity_prev_scene_id || '')
    setFromPrev(scene.continuity_from_previous || '')
    setToNext(scene.continuity_to_next || '')
  }, [scene.id, scene.continuity_prev_scene_id, scene.continuity_from_previous, scene.continuity_to_next])

  // Any scene in the episode except this one is a valid predecessor candidate.
  const candidates = scenes
    .filter(s => s.id !== scene.id)
    .sort((a, b) => a.order_index - b.order_index)

  async function save() {
    setBusy(true)
    try {
      await api.updateScene(scene.id, {
        continuity_prev_scene_id: prevId || null,
        continuity_from_previous: fromPrev.trim() || null,
        continuity_to_next: toNext.trim() || null,
      })
      onSaved?.()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="form-group mt-4" style={{ borderTop: '1px solid var(--border, #334155)', paddingTop: 12 }}>
      <label className="label">🔗 Continuity</label>
      <div className="form-group">
        <label className="label" style={{ fontWeight: 400, fontSize: '0.8rem' }}>Continues from scene</label>
        <select className="input" value={prevId} onChange={e => setPrevId(e.target.value)}
          style={{ width: '100%' }}>
          <option value="">Auto (smart chain — most recent scene sharing a character)</option>
          {candidates.map(s => (
            <option key={s.id} value={s.id}>
              Scene {s.order_index}{s.visual_summary ? ` — ${s.visual_summary.slice(0, 60)}` : ''}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted">
          Pin a non-adjacent predecessor (e.g. scene 8 continues scene 3). The render
          seeds this scene's first frame from that scene's last frame.
        </p>
      </div>
      <div className="grid-2">
        <div className="form-group">
          <label className="label" style={{ fontWeight: 400, fontSize: '0.8rem' }}>From previous (notes)</label>
          <textarea className="input" value={fromPrev} onChange={e => setFromPrev(e.target.value)}
            rows={2} style={{ width: '100%', fontSize: '0.8rem' }}
            placeholder="How this scene connects visually from its predecessor" />
        </div>
        <div className="form-group">
          <label className="label" style={{ fontWeight: 400, fontSize: '0.8rem' }}>To next (notes)</label>
          <textarea className="input" value={toNext} onChange={e => setToNext(e.target.value)}
            rows={2} style={{ width: '100%', fontSize: '0.8rem' }}
            placeholder="How this scene leads into the next" />
        </div>
      </div>
      <button className="btn btn-secondary btn-sm" disabled={busy} onClick={save}>
        {busy ? 'Saving…' : '💾 Save continuity'}
      </button>
    </div>
  )
}

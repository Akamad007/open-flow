import { useState, useEffect } from 'react'
import type { Scene, Character, Location } from '../types'
import { api } from '../api/client'

interface Props {
  scene: Scene
  characters: Character[]
  locations: Location[]
  onSaved?: () => void
}

export function ScenePromptDetail({ scene, characters, locations, onSaved }: Props) {
  const p = scene.prompt
  const [vp, setVp] = useState(p?.video_prompt || '')
  const [np, setNp] = useState(p?.negative_prompt || '')
  const [cap, setCap] = useState(scene.caption || '')
  const [busy, setBusy] = useState('')

  useEffect(() => {
    setVp(scene.prompt?.video_prompt || '')
    setNp(scene.prompt?.negative_prompt || '')
    setCap(scene.caption || '')
  }, [scene.id, scene.prompt?.video_prompt, scene.prompt?.negative_prompt, scene.caption])

  async function savePrompt(rerender: boolean) {
    setBusy(rerender ? 'Saving + re-rendering…' : 'Saving…')
    try {
      await api.updateScenePrompt(scene.id, { video_prompt: vp, negative_prompt: np })
      if (rerender) await api.regenerateScene(scene.id)
      onSaved?.()
    } finally {
      setBusy('')
    }
  }

  async function saveCaption() {
    setBusy('Saving caption…')
    try {
      await api.updateScene(scene.id, { caption: cap })
      onSaved?.()
    } finally {
      setBusy('')
    }
  }
  const sceneCharNames = scene.characters?.map(c => c.canonical_name).filter(Boolean) || []
  const loc = scene.location_id ? locations.find(l => l.id === scene.location_id) : null
  const charRefs = (scene.characters || []).map(sc =>
    characters.find(c => c.id === sc.id) || sc
  )

  return (
    <>
      <div className="form-group">
        <label className="label">Source Excerpt</label>
        <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
          {scene.source_excerpt || 'N/A'}
        </p>
      </div>
      <div className="form-group">
        <label className="label">Scene Purpose</label>
        <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
          {scene.scene_purpose || 'N/A'}
        </p>
      </div>
      <div className="form-group">
        <label className="label">Visual Summary</label>
        <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
          {scene.visual_summary || 'N/A'}
        </p>
      </div>

      <div className="form-group">
        <label className="label">📝 Caption (burned onto the video)</label>
        <textarea className="input" value={cap} onChange={e => setCap(e.target.value)}
          rows={2} spellCheck={false}
          placeholder={scene.visual_summary || 'Short on-screen caption explaining the scene & characters…'}
          style={{ width: '100%', fontSize: '0.85rem' }} />
        <div className="flex gap-2 items-center">
          <button className="btn btn-secondary btn-sm" disabled={!!busy} onClick={saveCaption}>💾 Save caption</button>
          {sceneCharNames.length > 0 && (
            <span className="text-xs text-muted">in scene: {sceneCharNames.join(', ')}</span>
          )}
        </div>
      </div>

      <div className="grid-2">
        <div className="form-group">
          <label className="label">📍 Location</label>
          <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            {loc ? loc.name : '—'}
          </p>
          {loc?.reference_image_path && (
            <img src={`/${loc.reference_image_path}`} alt={loc.name}
              style={{ width: '100%', maxWidth: 280, borderRadius: 6, marginTop: 4 }}
              onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
          )}
        </div>
        <div className="form-group">
          <label className="label">👤 Characters in scene</label>
          {charRefs.length === 0 ? (
            <p className="text-sm text-muted">—</p>
          ) : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {charRefs.map(c => (
                <div key={c.id} style={{ textAlign: 'center' }}>
                  {c.reference_image_path ? (
                    <img src={`/${c.reference_image_path}`} alt={c.canonical_name}
                      style={{ width: 60, height: 80, objectFit: 'cover', borderRadius: 6 }}
                      onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
                  ) : <div style={{ width: 60, height: 80, background: 'var(--color-surface-2)', borderRadius: 6 }} />}
                  <p style={{ fontSize: '0.7rem', marginTop: 2 }}>{c.canonical_name}</p>
                </div>
              ))}
            </div>
          )}
          {sceneCharNames.length === 0 && <p className="text-xs text-muted">No characters linked to this scene.</p>}
        </div>
      </div>

      {p && (
        <>
          <h3 className="card-title mt-4 mb-4">
            🎨 Video Prompt
            {p.approved && <span style={{ marginLeft: 8, fontSize: '0.7rem', padding: '2px 8px', borderRadius: 999, background: 'rgba(16,185,129,0.15)', color: '#10b981' }}>✓ critic-approved</span>}
            {!p.approved && <span style={{ marginLeft: 8, fontSize: '0.7rem', padding: '2px 8px', borderRadius: 999, background: 'rgba(245,158,11,0.15)', color: '#f59e0b' }}>pending review</span>}
          </h3>
          {p.lora_plan && (
            <div className="form-group">
              <label className="label">🎛️ LoRA stack (LLM-picked)</label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
                {p.lora_plan.loras.length === 0 ? (
                  <span style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: 999, background: 'rgba(148,163,184,0.15)', color: '#94a3b8' }}>
                    no LoRA (baseline)
                  </span>
                ) : p.lora_plan.loras.map(l => (
                  <span key={l.id} style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: 999, background: 'rgba(59,130,246,0.15)', color: '#3b82f6', fontFamily: 'monospace' }}>
                    {l.id}@{l.weight}
                  </span>
                ))}
                <span style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: 999, background: 'rgba(168,85,247,0.15)', color: '#a855f7' }}>
                  shot: {p.lora_plan.shot_type}
                </span>
              </div>
              {p.lora_plan.rationale && (
                <p className="text-xs text-muted mt-1" style={{ fontStyle: 'italic' }}>{p.lora_plan.rationale}</p>
              )}
            </div>
          )}
          <div className="form-group">
            <label className="label">Video prompt (paste to re-prompt — rendered verbatim)</label>
            <textarea className="input" value={vp} onChange={e => setVp(e.target.value)}
              rows={8} spellCheck={false} placeholder="Paste a video prompt here…"
              style={{ width: '100%', fontFamily: 'monospace', fontSize: '0.8rem', whiteSpace: 'pre-wrap' }} />
            <p className="text-xs text-muted">{vp.trim() ? `${vp.trim().split(/\s+/).length} words` : 'empty'}</p>
          </div>
          <div className="form-group">
            <label className="label">Negative prompt</label>
            <textarea className="input" value={np} onChange={e => setNp(e.target.value)}
              rows={3} spellCheck={false} placeholder="Negative prompt…"
              style={{ width: '100%', fontFamily: 'monospace', fontSize: '0.8rem', whiteSpace: 'pre-wrap' }} />
          </div>
          <div className="flex gap-2 items-center">
            <button className="btn btn-secondary btn-sm" disabled={!!busy}
              onClick={() => savePrompt(false)}>💾 Save prompt</button>
            <button className="btn btn-primary btn-sm" disabled={!!busy}
              onClick={() => savePrompt(true)}>💾 Save & re-render</button>
            {busy && <span className="text-xs text-muted">{busy}</span>}
          </div>
          {p.scene_breakdown && (
            <div className="form-group">
              <label className="label">Per-second breakdown</label>
              <pre className="text-sm text-muted" style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{p.scene_breakdown}</pre>
            </div>
          )}
          <div className="grid-2">
            <div className="form-group">
              <label className="label">Camera plan</label>
              <p className="text-sm text-muted">{p.camera_plan || 'N/A'}</p>
              {p.camera_angle && <p className="text-xs text-muted">angle: {p.camera_angle}</p>}
            </div>
            <div className="form-group">
              <label className="label">Style notes</label>
              <p className="text-sm text-muted">{p.style_notes || 'N/A'}</p>
            </div>
            <div className="form-group">
              <label className="label">Subject</label>
              <p className="text-sm text-muted">{p.subject_description || 'N/A'}</p>
            </div>
            <div className="form-group">
              <label className="label">Environment</label>
              <p className="text-sm text-muted">{p.environment_description || 'N/A'}</p>
            </div>
            <div className="form-group">
              <label className="label">Action</label>
              <p className="text-sm text-muted">{p.action_description || 'N/A'}</p>
            </div>
            <div className="form-group">
              <label className="label">Continuity guardrails</label>
              <p className="text-sm text-muted">{p.continuity_guardrails || 'N/A'}</p>
            </div>
          </div>
          {p.critic_notes && (
            <div className="form-group">
              <label className="label">Critic notes</label>
              <p className="text-sm" style={{ color: 'var(--accent-rose, #f87171)', whiteSpace: 'pre-wrap' }}>{p.critic_notes}</p>
            </div>
          )}
        </>
      )}
      <div className="form-group mt-4">
        <label className="label">Continuity</label>
        <p className="text-sm text-muted">From prev: {scene.continuity_from_previous || 'N/A'}</p>
        <p className="text-sm text-muted">To next: {scene.continuity_to_next || 'N/A'}</p>
        {(scene.target_audio_segment_start != null && scene.target_audio_segment_end != null) && (
          <p className="text-sm text-muted">
            🔊 Audio segment: {scene.target_audio_segment_start.toFixed(1)}s – {scene.target_audio_segment_end.toFixed(1)}s
          </p>
        )}
      </div>
    </>
  )
}

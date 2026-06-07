import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import type { ProjectListItem, PipelineProfile } from '../types'

interface RefRow {
  id: string
  label: string
  file: File | null
}

export function ProjectListPage() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<ProjectListItem[]>([])
  const [pipelines, setPipelines] = useState<PipelineProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [title, setTitle] = useState('')
  const [theme, setTheme] = useState('')
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [youtubeAsBg, setYoutubeAsBg] = useState(false)
  const [skipAudio, setSkipAudio] = useState(false)
  const [storyText, setStoryText] = useState('')
  const [targetDuration, setTargetDuration] = useState(300) // seconds
  const [pipelineProfile, setPipelineProfile] = useState('wan22_image_seeded')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  // Inline upload rows captured during project creation. We can't write Asset
  // rows until the project exists, so these stay client-side until submit.
  const [characterRefs, setCharacterRefs] = useState<RefRow[]>([
    { id: crypto.randomUUID(), label: '', file: null },
  ])
  const [productRefs, setProductRefs] = useState<RefRow[]>([
    { id: crypto.randomUUID(), label: '', file: null },
  ])

  const DURATION_OPTIONS = [
    { label: '1 min', value: 60 },
    { label: '2 min', value: 120 },
    { label: '5 min', value: 300 },
    { label: '10 min', value: 600 },
    { label: '15 min', value: 900 },
    { label: '30 min', value: 1800 },
  ]

  const loadProjects = async () => {
    try {
      const data = await api.listProjects()
      setProjects(data)
    } catch (e) {
      console.error('Failed to load projects:', e)
    } finally {
      setLoading(false)
    }
  }

  const loadPipelines = async () => {
    try {
      setPipelines(await api.listPipelines())
    } catch (e) {
      console.error('Failed to load pipelines:', e)
    }
  }

  useEffect(() => { loadProjects(); loadPipelines() }, [])

  const resetForm = () => {
    setTitle('')
    setTheme('')
    setYoutubeUrl('')
    setYoutubeAsBg(false)
    setSkipAudio(false)
    setStoryText('')
    setTargetDuration(300)
    setPipelineProfile('wan22_image_seeded')
    setCharacterRefs([{ id: crypto.randomUUID(), label: '', file: null }])
    setProductRefs([{ id: crypto.randomUUID(), label: '', file: null }])
    setCreateError(null)
  }

  const handleCreate = async () => {
    if (!title.trim()) return
    setCreateError(null)
    setCreating(true)
    try {
      const ytTrim = youtubeUrl.trim()
      const proj = await api.createProject({
        title: title.trim(),
        original_story_text: storyText,
        total_target_duration_seconds: targetDuration,
        pipeline_profile: pipelineProfile,
        theme_hint: theme.trim() || undefined,
        youtube_audio_url: ytTrim || undefined,
        skip_audio: skipAudio || undefined,
        youtube_as_background_music: (ytTrim && youtubeAsBg) ? true : undefined,
      })

      // Upload any character/product refs the user attached to the form.
      const uploads: Promise<unknown>[] = []
      for (const r of characterRefs) {
        if (r.file && r.label.trim()) {
          uploads.push(api.uploadCharacter(proj.id, r.label.trim(), r.file))
        }
      }
      for (const r of productRefs) {
        if (r.file && r.label.trim()) {
          uploads.push(api.uploadProduct(proj.id, r.label.trim(), r.file))
        }
      }
      if (uploads.length) {
        await Promise.all(uploads)
      }

      resetForm()
      setShowCreate(false)
      // Land on the project so the user can see the LLM pick up their refs.
      navigate(`/projects/${proj.id}?tab=uploads`)
    } catch (e) {
      console.error('Create failed:', e)
      setCreateError(String(e))
    } finally {
      setCreating(false)
    }
  }

  const updateRef = (
    setter: React.Dispatch<React.SetStateAction<RefRow[]>>,
    id: string, patch: Partial<RefRow>,
  ) => {
    setter(rows => rows.map(r => r.id === id ? { ...r, ...patch } : r))
  }
  const addRef = (setter: React.Dispatch<React.SetStateAction<RefRow[]>>) => {
    setter(rows => [...rows, { id: crypto.randomUUID(), label: '', file: null }])
  }
  const removeRef = (
    setter: React.Dispatch<React.SetStateAction<RefRow[]>>, id: string,
  ) => {
    setter(rows => rows.length === 1 ? rows : rows.filter(r => r.id !== id))
  }

  if (loading) return <div className="empty-state"><p>Loading projects...</p></div>

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Projects</h1>
          <p className="page-subtitle">Story-to-video generation projects</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(!showCreate)}>
          + New Project
        </button>
      </div>

      {showCreate && (
        <div className="card mb-4" style={{ marginBottom: 24 }}>
          <div className="form-group">
            <label className="label">Project Title</label>
            <input className="input" value={title} onChange={e => setTitle(e.target.value)}
              placeholder="My Story Video" />
          </div>
          <div className="form-group">
            <label className="label">Theme / Prompt (one line)</label>
            <p className="label-hint">We'll expand this into a full episode story. Leave blank if you'd rather paste full story text below.</p>
            <textarea
              className="textarea"
              value={theme}
              onChange={e => setTheme(e.target.value)}
              placeholder="e.g. A lighthouse keeper rows out to a storm-wrecked ship at dawn while gulls circle"
              rows={2}
            />
          </div>
          <div className="form-group">
            <label className="label">YouTube audio URL (optional)</label>
            <p className="label-hint">If set, the YouTube audio is overlaid on the rendered video and video length matches the clip.</p>
            <input
              className="input"
              type="url"
              value={youtubeUrl}
              onChange={e => setYoutubeUrl(e.target.value)}
              placeholder="https://youtu.be/..."
            />
            {youtubeUrl.trim() && (
              <label className="label" style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8, cursor: 'pointer', fontWeight: 'normal' }}>
                <input
                  type="checkbox"
                  checked={youtubeAsBg}
                  onChange={e => setYoutubeAsBg(e.target.checked)}
                />
                <span>Mix as background music under narration (keep voiceover; YT plays softly underneath)</span>
              </label>
            )}
          </div>
          <div className="form-group">
            <label className="label">
              Target Duration{youtubeUrl.trim() ? ' (auto from YouTube)' : ''}
            </label>
            <p className="label-hint">How long should the final video be?</p>
            <div className="duration-pills">
              {DURATION_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  className={`duration-pill ${targetDuration === opt.value ? 'active' : ''}`}
                  onClick={() => setTargetDuration(opt.value)}
                  disabled={!!youtubeUrl.trim()}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <div className="form-group">
            <label className="label" style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}>
              <input type="checkbox" checked={skipAudio} onChange={e => setSkipAudio(e.target.checked)} />
              <span>Silent background video (skip narration — overlay your own audio later)</span>
            </label>
          </div>
          <div className="form-group">
            <label className="label">Pipeline</label>
            <p className="label-hint">Which video model + pre-gen recipe to use</p>
            <select className="input" value={pipelineProfile} onChange={e => setPipelineProfile(e.target.value)}>
              {pipelines.map(p => (
                <option key={p.name} value={p.name}>
                  {p.name} — {p.recommended_for}
                </option>
              ))}
            </select>
            {pipelines.find(p => p.name === pipelineProfile) && (
              <p className="label-hint" style={{ marginTop: 4 }}>
                {pipelines.find(p => p.name === pipelineProfile)?.description}
              </p>
            )}
          </div>

          <RefRowsSection
            title="Character references (optional)"
            help="Upload a face/full-body shot for each character in your story. The label must contain a word that matches the character name (case-insensitive)."
            rows={characterRefs}
            onUpdate={(id, patch) => updateRef(setCharacterRefs, id, patch)}
            onAdd={() => addRef(setCharacterRefs)}
            onRemove={(id) => removeRef(setCharacterRefs, id)}
            labelPlaceholder='Character name (e.g. "Alice")'
          />

          <RefRowsSection
            title="Product references (optional)"
            help="Upload a hero shot for each product in your story. The label must contain a word that matches the product name (case-insensitive)."
            rows={productRefs}
            onUpdate={(id, patch) => updateRef(setProductRefs, id, patch)}
            onAdd={() => addRef(setProductRefs)}
            onRemove={(id) => removeRef(setProductRefs, id)}
            labelPlaceholder='Product name (e.g. "tan leather handbag")'
          />

          <div className="form-group">
            <label className="label">Story Text (optional — can add later)</label>
            <textarea className="textarea" value={storyText} onChange={e => setStoryText(e.target.value)}
              placeholder="Paste your story here..." />
          </div>
          {createError && (
            <div style={{ color: '#c00', padding: 8, border: '1px solid #c00', borderRadius: 4, marginBottom: 8 }}>
              {createError}
            </div>
          )}
          <div className="flex gap-2">
            <button className="btn btn-primary" onClick={handleCreate} disabled={creating || !title.trim()}>
              {creating ? 'Creating...' : 'Create Project'}
            </button>
            <button className="btn btn-secondary" onClick={() => { resetForm(); setShowCreate(false) }}>Cancel</button>
          </div>
        </div>
      )}

      {projects.length === 0 ? (
        <div className="empty-state">
          <h3>No projects yet</h3>
          <p>Create your first story-to-video project to get started.</p>
        </div>
      ) : (
        <div className="grid-auto">
          {projects.map(p => (
            <div key={p.id} className="project-card" style={{ position: 'relative' }}>
              <Link to={`/projects/${p.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
                <div className="flex items-center justify-between">
                  <span className="project-card-title">{p.title}</span>
                  <StatusBadge status={p.status} />
                </div>
                <div className="project-card-meta">
                  <span>🎬 {p.scene_count} scenes</span>
                  {p.total_target_duration_seconds && (
                    <span>⏱️ {Math.round(p.total_target_duration_seconds / 60)} min</span>
                  )}
                  <span>⚙️ {p.pipeline_profile}</span>
                  <span>📅 {new Date(p.created_at).toLocaleDateString()}</span>
                </div>
              </Link>
              <button
                className="btn-delete-card"
                title="Delete project"
                onClick={async (e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  if (window.confirm(`Delete "${p.title}"? This cannot be undone.`)) {
                    await api.deleteProject(p.id)
                    loadProjects()
                  }
                }}
              >🗑️</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


interface RefRowsSectionProps {
  title: string
  help: string
  rows: RefRow[]
  labelPlaceholder: string
  onUpdate: (id: string, patch: Partial<RefRow>) => void
  onAdd: () => void
  onRemove: (id: string) => void
}

function RefRowsSection({ title, help, rows, labelPlaceholder, onUpdate, onAdd, onRemove }: RefRowsSectionProps) {
  return (
    <div className="form-group">
      <label className="label">{title}</label>
      <p className="label-hint">{help}</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map(r => (
          <div key={r.id} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              className="input"
              style={{ flex: '1 1 200px', minWidth: 180 }}
              placeholder={labelPlaceholder}
              value={r.label}
              onChange={e => onUpdate(r.id, { label: e.target.value })}
            />
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={e => onUpdate(r.id, { file: e.target.files?.[0] || null })}
            />
            {r.file && <span style={{ fontSize: 12, color: '#0a0' }}>✓ {r.file.name}</span>}
            <button
              type="button"
              className="btn btn-secondary"
              style={{ padding: '4px 10px' }}
              onClick={() => onRemove(r.id)}
              disabled={rows.length === 1}
              title={rows.length === 1 ? 'Keep at least one row' : 'Remove this row'}
            >
              −
            </button>
          </div>
        ))}
        <button type="button" className="btn btn-secondary" style={{ alignSelf: 'flex-start', padding: '4px 12px' }} onClick={onAdd}>
          + Add another
        </button>
      </div>
    </div>
  )
}

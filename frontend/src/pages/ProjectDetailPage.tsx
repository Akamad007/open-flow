import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import { JsonInspector } from '../components/JsonInspector'
import { StoryAnalysis } from '../components/StoryAnalysis'
import { ScenePromptDetail } from '../components/ScenePromptDetail'
import { AudioTimingMap } from '../components/AudioTimingMap'
import { StageJobPanel } from '../components/StageJobPanel'
import { LogsPanel } from '../components/LogsPanel'
import { EvalPanel } from '../components/EvalPanel'
import { CriticReviewSummary, SceneCriticIssues } from '../components/CriticIssues'
import { StillCriticAll, StillCriticForScene } from '../components/StillCriticVerdicts'
import { UploadsManager } from '../components/UploadsManager'
import { EpisodesPanel } from '../components/EpisodesPanel'
import type { Project, Scene, Character, Location, AudioPlan, Asset, RenderJob, ProjectImages, EpisodeListItem } from '../types'

type Tab = 'story' | 'scenes' | 'audio' | 'characters' | 'locations' | 'assets' | 'jobs' | 'logs' | 'eval' | 'render' | 'images' | 'uploads'

const assetUrl = (asset: { id: string; file_path: string | null }) => {
  const name = asset.file_path?.split('/').pop()
  return name ? `/api/assets/${asset.id}/file/${name}` : `/api/assets/${asset.id}/file`
}

export function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const initialTab = (searchParams.get('tab') as Tab) || 'story'
  const [tab, setTab] = useState<Tab>(initialTab)

  const changeTab = useCallback((t: Tab) => {
    setTab(t)
    setSearchParams({ tab: t }, { replace: true })
  }, [setSearchParams])
  const [allScenes, setScenes] = useState<Scene[]>([])
  const [characters, setCharacters] = useState<Character[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [audioPlan, setAudioPlan] = useState<AudioPlan | null>(null)
  const [allAssets, setAssets] = useState<Asset[]>([])
  const [jobs, setJobs] = useState<RenderJob[]>([])
  const [episodes, setEpisodes] = useState<EpisodeListItem[]>([])
  const initialEpisodeId = searchParams.get('episode')
  const [selectedEpisodeId, setSelectedEpisodeIdState] = useState<string | null>(initialEpisodeId)
  const setSelectedEpisodeId = useCallback((id: string | null) => {
    setSelectedEpisodeIdState(id)
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (id) next.set('episode', id); else next.delete('episode')
      return next
    }, { replace: true })
  }, [setSearchParams])
  const [projectImages, setProjectImages] = useState<ProjectImages | null>(null)
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState('')
  const [storyText, setStoryText] = useState('')
  const [toasts, setToasts] = useState<{id: number; msg: string; type: 'success'|'error'}[]>([])

  const toast = (msg: string, type: 'success'|'error' = 'success') => {
    const id = Date.now()
    setToasts(t => [...t, { id, msg, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000)
  }

  const [loadError, setLoadError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!projectId) return
    setLoadError(null)
    try {
      const [p, s, c, l, a, j, imgs, eps] = await Promise.all([
        api.getProject(projectId),
        api.listScenes(projectId),
        api.listCharacters(projectId),
        api.listLocations(projectId),
        api.listAssets(projectId),
        api.listJobs(projectId),
        api.getProjectImages(projectId).catch(() => null),
        api.listEpisodes(projectId).catch(() => [] as EpisodeListItem[]),
      ])
      setProject(p); setScenes(s); setCharacters(c);
      setLocations(l); setAssets(a); setJobs(j);
      setProjectImages(imgs); setEpisodes(eps)
      setStoryText(p.original_story_text)
    } catch (e: any) {
      console.error('load failed:', e)
      setLoadError(e?.message || String(e))
    }
    finally { setLoading(false) }
  }, [projectId])

  // Default-select an episode after load (URL > active > latest).
  useEffect(() => {
    if (episodes.length === 0) return
    const valid = selectedEpisodeId && episodes.some(e => e.id === selectedEpisodeId)
    if (valid) return
    const active = episodes.find(e => e.status !== 'complete' && e.status !== 'failed')
    const latest = episodes[episodes.length - 1]
    setSelectedEpisodeId((active ?? latest).id)
  }, [episodes, selectedEpisodeId, setSelectedEpisodeId])

  // Fetch the selected episode's audio plan separately (one plan per episode).
  useEffect(() => {
    let cancelled = false
    if (!selectedEpisodeId) { setAudioPlan(null); return }
    api.getEpisodeAudioPlan(selectedEpisodeId)
      .then(ap => { if (!cancelled) setAudioPlan(ap) })
      .catch(() => { if (!cancelled) setAudioPlan(null) })
    return () => { cancelled = true }
  }, [selectedEpisodeId])

  useEffect(() => { load() }, [load])

  // Auto-poll when jobs are running OR when the project is still actively processing
  useEffect(() => {
    const TERMINAL_STATUSES = new Set(['done', 'failed', 'draft', 'complete'])
    const hasRunningJobs = jobs.some(j => j.status === 'queued' || j.status === 'running')
    const projectIsActive = project && !TERMINAL_STATUSES.has(project.status)
    const hasGeneratingAssets = allAssets.some(a => a.status === 'generating' || a.status === 'pending')

    if (!hasRunningJobs && !projectIsActive && !hasGeneratingAssets) return
    const timer = setInterval(load, 3000)
    return () => clearInterval(timer)
  }, [jobs, allAssets, project, load])

  const runAction = async (name: string, fn: () => Promise<unknown>, successMsg = 'Done — refreshing...') => {
    setActionLoading(name)
    try {
      await fn()
      toast(successMsg, 'success')
      setTimeout(load, 1000)
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || String(e)
      toast(`❌ ${msg}`, 'error')
      console.error(e)
    } finally {
      setActionLoading('')
    }
  }

  const saveStory = async () => {
    if (!projectId) return
    await api.updateProject(projectId, { original_story_text: storyText })
    await load()
  }

  if (loading) return <div className="empty-state"><p>Loading project...</p></div>
  if (loadError) return (
    <div className="empty-state">
      <h3 style={{ color: 'var(--color-danger, #ef4444)' }}>❌ Failed to load project</h3>
      <pre style={{ marginTop: '1rem', fontSize: '0.8rem', color: 'var(--color-muted)', whiteSpace: 'pre-wrap', textAlign: 'left', maxWidth: 600 }}>{loadError}</pre>
      <button className="btn btn-secondary btn-sm" style={{ marginTop: '1rem' }} onClick={load}>↺ Retry</button>
    </div>
  )
  if (!project || !projectId) return <div className="empty-state"><h3>Project not found</h3></div>

  // Scope per-scene + per-episode data to the selected episode. Characters /
  // locations / jobs / images stay project-wide (they're shared across
  // episodes). When no episode is selected (legacy view) everything passes
  // through unfiltered.
  const scenes: Scene[] = selectedEpisodeId
    ? allScenes.filter(s => s.episode_id === selectedEpisodeId)
    : allScenes
  const filteredSceneIds = new Set(scenes.map(s => s.id))
  const assets: Asset[] = selectedEpisodeId
    ? allAssets.filter(a =>
        a.episode_id === selectedEpisodeId
        || (a.scene_id && filteredSceneIds.has(a.scene_id))
        || (!a.episode_id && !a.scene_id)
      )
    : allAssets

  const tabs: { key: Tab; label: string }[] = [
    { key: 'story',      label: '📝 Story' },
    { key: 'uploads',    label: '📤 Uploads' },
    { key: 'characters', label: `👤 Characters (${characters.length})` },
    { key: 'locations',  label: `📍 Locations (${locations.length})` },
    { key: 'images',     label: `🎨 Images` },
    { key: 'scenes',     label: `🎬 Scenes (${scenes.length})` },
    { key: 'audio',      label: '🔊 Audio Plan' },
    { key: 'assets',     label: `📦 Assets (${assets.length})` },
    { key: 'jobs',       label: `⚙️ Jobs (${jobs.length})` },
    { key: 'logs',       label: '📜 Logs' },
    { key: 'eval',       label: '📊 Eval' },
    { key: 'render',     label: '🎥 Render' },
  ]

  return (
    <>
      <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">{project.title}</h1>
          <div className="flex items-center gap-2 mt-2">
            <StatusBadge status={project.status} />
            {project.total_target_duration_seconds && (
              <span className="text-sm text-muted">
                ⏱️ {project.total_target_duration_seconds.toFixed(1)}s total
              </span>
            )}
            <span className="text-sm text-muted" title="Pipeline profile">
              ⚙️ {project.pipeline_profile}
            </span>
            <span className="text-sm text-muted" title="Project ID">
              🆔 {project.id.slice(0, 8)}
            </span>
          </div>
        </div>
        <button
          className="btn btn-danger btn-sm"
          onClick={async () => {
            if (window.confirm(`Delete "${project.title}"? This cannot be undone.`)) {
              await api.deleteProject(projectId)
              navigate('/')
            }
          }}
        >🗑️ Delete</button>
      </div>

      {/* Episodes — multi-episode support inside a project */}
      <EpisodesPanel
        projectId={projectId!}
        selectedEpisodeId={selectedEpisodeId}
        onSelect={setSelectedEpisodeId}
        onCreated={load}
        onDeleted={load}
      />

      {/* Error Banner — show last failure reason */}
      {project.status === 'failed' && (() => {
        const failedJobs = jobs.filter(j => j.status === 'failed' && j.error_text)
        const lastFailed = failedJobs[0]
        return lastFailed ? (
          <div className="error-banner">
            <div className="error-banner-header">
              <span>❌ Pipeline failed at <strong>{lastFailed.job_type.replace(/_/g, ' ')}</strong></span>
            </div>
            <pre className="error-banner-detail">{lastFailed.error_text}</pre>
          </div>
        ) : null
      })()}

      {/* Action Bar */}
      <div className="action-bar">
        <button className="btn btn-primary btn-sm" disabled={!!actionLoading}
          onClick={() => runAction('pipeline', () => api.generateAll(projectId), '🚀 Full pipeline queued!')}>
          {actionLoading === 'pipeline' ? '⏳ Running...' : '🚀 Run Full Pipeline'}
        </button>
        <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
          onClick={() => runAction('analyze', () => api.analyzeStory(projectId), '📊 Story analysis queued')}>
          {actionLoading === 'analyze' ? '⏳...' : '📊 Analyze Story'}
        </button>
        <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
          onClick={() => runAction('plan', () => api.planScenes(projectId), '✂️ Scene planning queued')}>
          {actionLoading === 'plan' ? '⏳...' : '✂️ Plan Scenes'}
        </button>
        <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
          onClick={() => runAction('prompts', () => api.generatePrompts(projectId), '🎨 Prompt generation queued')}>
          {actionLoading === 'prompts' ? '⏳...' : '🎨 Generate Prompts'}
        </button>
        <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
          onClick={() => runAction('audio', () => api.planAudio(projectId), '🔊 Audio planning queued')}>
          {actionLoading === 'audio' ? '⏳...' : '🔊 Plan Audio'}
        </button>
        <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
          onClick={() => runAction('review', () => api.reviewConsistency(projectId), '🔍 Consistency review queued')}>
          {actionLoading === 'review' ? '⏳...' : '🔍 Review'}
        </button>
        <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
          onClick={() => runAction('videos', () => api.generateVideos(projectId), '🎬 Video generation queued')}>
          {actionLoading === 'videos' ? '⏳...' : '🎬 Gen Videos'}
        </button>
        <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
          onClick={() => runAction('genAudio', () => api.generateAudio(projectId), '🎵 Audio generation queued')}>
          {actionLoading === 'genAudio' ? '⏳...' : '🎵 Gen Audio'}
        </button>
        <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
          onClick={() => runAction('stitch', () => api.stitch(projectId), '🧵 Stitching queued')}>
          {actionLoading === 'stitch' ? '⏳...' : '🧵 Stitch'}
        </button>
      </div>

      {/* Tabs */}
      <div className="tabs">
        {tabs.map(t => (
          <button key={t.key} className={`tab ${tab === t.key ? 'active' : ''}`}
            onClick={() => changeTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {tab === 'story' && (
        <div>
          <div className="form-group">
            <label className="label">Story Text</label>
            <textarea className="textarea textarea-large" value={storyText}
              onChange={e => setStoryText(e.target.value)}
              placeholder="Paste your story here..." />
          </div>
          <button className="btn btn-primary" onClick={saveStory}>💾 Save Story</button>
          <StoryAnalysis project={project} />
          <div className="mt-4">
            <StageJobPanel
              title="Stage 1 — Story Analysis (job)"
              jobTypes={['story_analysis']}
              jobs={jobs}
              onRetry={() => api.analyzeStory(projectId!).then(load)}
              retryDisabled={!!actionLoading}
            />
          </div>
          {(characters.length > 0 || locations.length > 0) && (
            <div className="card mt-4">
              <h3 className="card-title">📋 Stage 1 outputs</h3>
              <p className="text-xs text-muted" style={{ marginTop: 4 }}>
                {characters.length} character{characters.length === 1 ? '' : 's'} ·{' '}
                {locations.length} location{locations.length === 1 ? '' : 's'} extracted.
                See the <strong>Characters</strong> and <strong>Locations</strong> tabs for details.
              </p>
            </div>
          )}
        </div>
      )}

      {tab === 'uploads' && (
        <div>
          <h2 style={{ marginTop: 0 }}>Reference images</h2>
          <p style={{ color: '#666', fontSize: 14 }}>
            Upload your own character or product images. The pipeline will use them
            instead of generating synthetic refs — required for identity-locked or
            brand-faithful ads. Match the label to the character/product name as
            it appears in your story.
          </p>
          <UploadsManager projectId={projectId!} />
        </div>
      )}

      {tab === 'scenes' && (
        <div>
          <div className="flex-col gap-4 mb-4">
            <StageJobPanel
              title="Stage 2 — Scene Planning"
              jobTypes={['scene_planning']}
              jobs={jobs}
              onRetry={() => api.planScenes(projectId!).then(load)}
              retryDisabled={!!actionLoading}
            />
            <StageJobPanel
              title="Stage 3 — Visual Director (per-scene prompts)"
              jobTypes={['prompt_generation']}
              jobs={jobs}
              onRetry={() => api.generatePrompts(projectId!).then(load)}
              retryDisabled={!!actionLoading}
            />
            <CriticReviewSummary jobs={jobs} />
            <StageJobPanel
              title="Stage 5 — Consistency Critic (job)"
              jobTypes={['consistency_review']}
              jobs={jobs}
              onRetry={() => api.reviewConsistency(projectId!).then(load)}
              retryDisabled={!!actionLoading}
            />
            <StageJobPanel
              title="Stage 7 — Scene Video Generation (per-scene LTX)"
              jobTypes={['video_generation']}
              jobs={jobs}
              onRetry={() => api.generateVideos(projectId!).then(load)}
              retryDisabled={!!actionLoading}
            />
          </div>
          {scenes.length === 0 ? (
            <div className="empty-state"><h3>No scenes yet</h3><p>Run "Plan Scenes" to generate scene breakdowns.</p></div>
          ) : (
            <>
              <div className="section-actions">
                <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
                  onClick={() => runAction('prompts', () => api.generatePrompts(projectId!))}>
                  {actionLoading === 'prompts' ? '⏳ Running...' : '🎨 Regenerate All Prompts'}
                </button>
                <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
                  onClick={() => runAction('videos', () => api.regenerateAllVideos(projectId!), '🎬 Force-regenerating all videos...')}>
                  {actionLoading === 'videos' ? '⏳ Running...' : '🎬 Regenerate All Videos'}
                </button>
                <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
                  onClick={() => runAction('review', () => api.reviewConsistency(projectId!))}>
                  {actionLoading === 'review' ? '⏳ Running...' : '🔍 Re-Review Consistency'}
                </button>
              </div>
              <div className="scene-board">
                {scenes.map(scene => {
                  const sceneVideo = assets.find(a => a.scene_id === scene.id && a.asset_type === 'scene_video')
                  return (
                    <div key={scene.id} className={`scene-card ${scene.locked ? 'locked' : ''}`}
                      onClick={() => setSelectedScene(scene)}>
                      <div className="scene-card-header">
                        <span className="scene-number">Scene {scene.order_index}</span>
                        <div className="flex items-center gap-2">
                          <span className="scene-duration">{scene.duration_seconds}s</span>
                          <StatusBadge status={scene.status} />
                          {scene.locked && <span title="Locked">🔒</span>}
                        </div>
                      </div>
                      {scene.prompt?.lora_plan && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, margin: '4px 0' }}
                             title={scene.prompt.lora_plan.rationale || ''}>
                          {scene.prompt.lora_plan.loras.length === 0 ? (
                            <span style={{ fontSize: '0.65rem', padding: '1px 6px', borderRadius: 999, background: 'rgba(148,163,184,0.15)', color: '#94a3b8' }}>
                              no LoRA
                            </span>
                          ) : scene.prompt.lora_plan.loras.map(l => (
                            <span key={l.id} style={{ fontSize: '0.65rem', padding: '1px 6px', borderRadius: 999, background: 'rgba(59,130,246,0.15)', color: '#3b82f6', fontFamily: 'monospace' }}>
                              {l.id}@{l.weight}
                            </span>
                          ))}
                          <span style={{ fontSize: '0.65rem', padding: '1px 6px', borderRadius: 999, background: 'rgba(168,85,247,0.15)', color: '#a855f7' }}>
                            {scene.prompt.lora_plan.shot_type}
                          </span>
                        </div>
                      )}
                      {sceneVideo && sceneVideo.file_path && (
                        <div className="scene-video-preview">
                          <video
                            src={assetUrl(sceneVideo)}
                            muted loop autoPlay playsInline controls preload="metadata"
                            onClick={e => e.stopPropagation()}
                          />
                        </div>
                      )}
                      {scene.visual_summary && (
                        <p className="scene-excerpt">{scene.visual_summary}</p>
                      )}
                      {scene.prompt?.video_prompt && (
                        <div className="scene-prompt-preview">{scene.prompt.video_prompt}</div>
                      )}
                      {scene.target_audio_segment_start !== null && scene.target_audio_segment_end !== null && (
                        <p className="text-xs text-muted mt-2">
                          🔊 Audio: {scene.target_audio_segment_start.toFixed(1)}s – {scene.target_audio_segment_end.toFixed(1)}s
                        </p>
                      )}
                      <SceneCriticIssues jobs={jobs} sceneIndex={scene.order_index} />
                      <StillCriticForScene jobs={jobs} sceneIndex={scene.order_index} />
                      <div className="scene-card-actions" onClick={e => e.stopPropagation()}>
                        <button className="btn-icon" title="Regenerate video"
                          disabled={!!actionLoading}
                          onClick={() => runAction(`regen-${scene.id}`, () => api.regenerateScene(scene.id))}>
                          🔄
                        </button>
                        {sceneVideo && sceneVideo.status === 'failed' && (
                          <span className="text-xs" style={{ color: 'var(--accent-rose)' }}>Failed</span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </div>
      )}

      {tab === 'audio' && (
        <div>
          <div className="flex-col gap-4 mb-4">
            <StageJobPanel
              title="Stage 4 — Audio Director (plan)"
              jobTypes={['audio_planning']}
              jobs={jobs}
              onRetry={() => api.planAudio(projectId!).then(load)}
              retryDisabled={!!actionLoading}
            />
            <StageJobPanel
              title="Stage 8 — Audio Generation (Chatterbox TTS)"
              jobTypes={['audio_generation']}
              jobs={jobs}
              onRetry={() => api.generateAudio(projectId!).then(load)}
              retryDisabled={!!actionLoading}
            />
          </div>
          <div className="section-actions">
            <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
              onClick={() => runAction('planAudio', () => api.planAudio(projectId!))}>
              {actionLoading === 'planAudio' ? '⏳ Running...' : '🔊 Rerun Audio Plan'}
            </button>
            <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
              onClick={() => runAction('genAudio', () => api.generateAudio(projectId!))}>
              {actionLoading === 'genAudio' ? '⏳ Running...' : '🎵 Rerun Audio Generation'}
            </button>
            {(() => {
              const audioAsset = assets.find(a => a.asset_type === 'full_story_audio')
              if (audioAsset && audioAsset.status === 'complete') return (
                <span className="badge badge-complete">Audio Generated ✓</span>
              )
              if (audioAsset && audioAsset.status === 'failed') return (
                <span className="badge badge-failed">Audio Failed</span>
              )
              if (audioAsset && (audioAsset.status === 'generating' || audioAsset.status === 'pending')) return (
                <span className="badge badge-running">Generating...</span>
              )
              return null
            })()}
          </div>
          {!audioPlan ? (
            <div className="empty-state"><h3>No audio plan yet</h3><p>Run "Plan Audio" to generate the full-story audio plan.</p></div>
          ) : (
            <div className="flex-col gap-4">
              <div className="card">
                <h3 className="card-title">📝 Full Story Narration</h3>
                <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>
                  {audioPlan.full_story_narration_text || 'N/A'}
                </p>
              </div>
              <div className="card mt-4">
                <h3 className="card-title">🔊 Audio Prompt <span style={{ fontSize: '0.7rem', color: 'var(--color-muted)', fontWeight: 400 }}>(voice/style for TTS)</span></h3>
                <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}>
                  {audioPlan.full_story_audio_prompt || 'N/A'}
                </p>
              </div>
              {audioPlan.full_story_dialogue_plan && (
                <div className="card mt-4">
                  <h3 className="card-title">💬 Dialogue Plan</h3>
                  <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>
                    {audioPlan.full_story_dialogue_plan}
                  </p>
                </div>
              )}
              <AudioTimingMap raw={audioPlan.timing_map_json} />
              <div className="grid-2 mt-4">
                <div className="card">
                  <h3 className="card-title">🌊 Ambience Progression</h3>
                  <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}>
                    {audioPlan.ambience_progression_notes || 'N/A'}
                  </p>
                </div>
                <div className="card">
                  <h3 className="card-title">🔀 Sound Transitions</h3>
                  <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}>
                    {audioPlan.sound_transition_notes || 'N/A'}
                  </p>
                </div>
              </div>
              {audioPlan.total_estimated_audio_duration && (
                <p className="text-sm text-muted mt-4">
                  ⏱️ Estimated duration: {audioPlan.total_estimated_audio_duration.toFixed(1)}s
                </p>
              )}
              {/* Audio player if generated */}
              {(() => {
                const audioAsset = assets.find(a => (a.asset_type === 'full_story_audio') && a.status === 'complete')
                return audioAsset ? (
                  <div className="card mt-4">
                    <h3 className="card-title">🎧 Generated Audio</h3>
                    <audio controls className="mt-2" style={{ width: '100%' }}>
                      <source src={assetUrl(audioAsset)} />
                    </audio>
                  </div>
                ) : null
              })()}
            </div>
          )}
        </div>
      )}

      {tab === 'characters' && (
        <>
        <div className="mb-4">
          <StageJobPanel
            title="Stage 1 — Story Analysis (extracts characters)"
            jobTypes={['story_analysis']}
            jobs={jobs}
            onRetry={() => api.analyzeStory(projectId!).then(load)}
            retryDisabled={!!actionLoading}
          />
        </div>
        <div className="grid-auto">
          {characters.length === 0 ? (
            <div className="empty-state"><h3>No characters yet</h3></div>
          ) : characters.map(c => (
            <div key={c.id} className="card">
              <h3 className="card-title">👤 {c.canonical_name}</h3>
              {c.reference_image_path && (
                <img src={`/${c.reference_image_path}`} alt={c.canonical_name}
                  style={{ width: '100%', maxWidth: 220, aspectRatio: '3/4', objectFit: 'cover', borderRadius: 8, marginTop: 8 }}
                  onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
              )}
              {c.physical_description && <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}><strong>Physical:</strong> {c.physical_description}</p>}
              {c.clothing_description && <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}><strong>Clothing:</strong> {c.clothing_description}</p>}
              {c.personality_notes && <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}><strong>Personality:</strong> {c.personality_notes}</p>}
              {c.voice_notes && <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}><strong>Voice:</strong> {c.voice_notes}</p>}
              {c.continuity_notes && <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}><strong>Continuity:</strong> {c.continuity_notes}</p>}
              {(() => {
                const sceneNames = scenes
                  .filter(s => (s.characters || []).some(sc => sc.id === c.id))
                  .map(s => s.order_index)
                return sceneNames.length > 0 ? (
                  <p className="text-xs text-muted mt-2">📍 in scenes: {sceneNames.join(', ')}</p>
                ) : null
              })()}
            </div>
          ))}
        </div>
        </>
      )}

      {tab === 'locations' && (
        <>
        <div className="mb-4">
          <StageJobPanel
            title="Stage 1 — Story Analysis (extracts locations)"
            jobTypes={['story_analysis']}
            jobs={jobs}
            onRetry={() => api.analyzeStory(projectId!).then(load)}
            retryDisabled={!!actionLoading}
          />
        </div>
        <div className="grid-auto">
          {locations.length === 0 ? (
            <div className="empty-state"><h3>No locations yet</h3></div>
          ) : locations.map(l => {
            const sceneCount = scenes.filter(s => s.location_id === l.id).length
            return (
              <div key={l.id} className="card">
                <h3 className="card-title">📍 {l.name} <span style={{ fontSize: '0.7rem', color: 'var(--color-muted)', fontWeight: 400 }}>· {sceneCount} scene{sceneCount === 1 ? '' : 's'}</span></h3>
                {l.reference_image_path && (
                  <img src={`/${l.reference_image_path}`} alt={l.name}
                    style={{ width: '100%', aspectRatio: '16/9', objectFit: 'cover', borderRadius: 8, marginTop: 8 }}
                    onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
                )}
                {l.description && <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}>{l.description}</p>}
                {l.continuity_notes && <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}><strong>Continuity:</strong> {l.continuity_notes}</p>}
                {(() => {
                  const ix = scenes.filter(s => s.location_id === l.id).map(s => s.order_index)
                  return ix.length > 0 ? (
                    <p className="text-xs text-muted mt-2">🎬 used in scenes: {ix.join(', ')}</p>
                  ) : null
                })()}
              </div>
            )
          })}
        </div>
        </>
      )}

      {tab === 'assets' && (
        <div className="table-container">
          {assets.length === 0 ? (
            <div className="empty-state"><h3>No assets yet</h3></div>
          ) : (
            <table>
              <thead><tr>
                <th>Type</th><th>Status</th><th>Provider</th><th>Scene</th><th>Path & Metadata</th><th>Created</th><th>Actions</th>
              </tr></thead>
              <tbody>
                {assets.map(a => (
                  <tr key={a.id}>
                    <td>{a.asset_type.replace(/_/g, ' ')}</td>
                    <td><StatusBadge status={a.status} /></td>
                    <td>{a.generation_provider || '—'}</td>
                    <td>{a.scene_id ? `Scene ${(scenes.find(s => s.id === a.scene_id)?.order_index ?? -1) + 1}` : '—'}</td>
                    <td style={{ maxWidth: 380 }}>
                      {a.file_path ? (
                        <a href={assetUrl(a)} target="_blank" rel="noopener noreferrer"
                           className="text-xs" style={{ wordBreak: 'break-all', margin: 0, display: 'block' }}>
                          {a.file_path}
                        </a>
                      ) : (
                        <p className="text-xs text-muted" style={{ margin: 0 }}>—</p>
                      )}
                      <JsonInspector label="metadata_json" raw={a.metadata_json} />
                      <JsonInspector label="generation_params_json" raw={a.generation_params_json} />
                    </td>
                    <td>{new Date(a.created_at).toLocaleString()}</td>
                    <td>
                      {a.status === 'failed' && a.asset_type === 'scene_video' && a.scene_id && (
                        <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
                          onClick={() => runAction(`retry-asset-${a.id}`, () => api.regenerateScene(a.scene_id!))}>
                          🔄 Retry
                        </button>
                      )}
                      {a.status === 'failed' && (a.asset_type === 'full_story_audio') && (
                        <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
                          onClick={() => runAction(`retry-audio-${a.id}`, () => api.generateAudio(projectId!))}>
                          🔄 Retry
                        </button>
                      )}
                      {a.status === 'failed' && a.asset_type === 'final_render' && (
                        <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
                          onClick={() => runAction(`retry-stitch-${a.id}`, () => api.stitch(projectId!))}>
                          🔄 Retry
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === 'jobs' && (
        <div className="table-container">
          {jobs.length === 0 ? (
            <div className="empty-state"><h3>No jobs yet</h3></div>
          ) : (
            <table>
              <thead><tr>
                <th>Type</th><th>Status</th><th>Duration</th><th>Inputs / Outputs / Errors</th><th>Created</th><th>Actions</th>
              </tr></thead>
              <tbody>
                {[...jobs].sort((a, b) => {
                  const ORDER: Record<string, number> = {
                    full_pipeline: 0, story_analysis: 1, scene_planning: 2,
                    prompt_generation: 3, audio_planning: 4, consistency_review: 5,
                    image_pregen: 6, video_generation: 7, audio_generation: 8, stitching: 9,
                  }
                  return (ORDER[a.job_type] ?? 99) - (ORDER[b.job_type] ?? 99)
                }).map(j => {
                  const retryMap: Record<string, () => Promise<unknown>> = {
                    story_analysis: () => api.analyzeStory(projectId!),
                    scene_planning: () => api.planScenes(projectId!),
                    prompt_generation: () => api.generatePrompts(projectId!),
                    audio_planning: () => api.planAudio(projectId!),
                    consistency_review: () => api.reviewConsistency(projectId!),
                    video_generation: () => api.generateVideos(projectId!),
                    audio_generation: () => api.generateAudio(projectId!),
                    stitching: () => api.stitch(projectId!),
                  }
                  const durMs = new Date(j.updated_at).getTime() - new Date(j.created_at).getTime()
                  const durTxt = durMs > 1500 ? `${(durMs / 1000).toFixed(1)}s` : '—'
                  return (
                    <tr key={j.id}>
                      <td>
                        {j.job_type.replace(/_/g, ' ')}
                        {j.job_type_detail && <span className="text-xs text-muted"> · {j.job_type_detail}</span>}
                      </td>
                      <td><StatusBadge status={j.status} /></td>
                      <td style={{ whiteSpace: 'nowrap' }}>{durTxt}</td>
                      <td style={{ maxWidth: 480 }}>
                        {j.error_text ? (
                          <details>
                            <summary className="error-summary">{j.error_text.substring(0, 80)}{j.error_text.length > 80 ? '...' : ''}</summary>
                            <pre className="error-detail">{j.error_text}</pre>
                          </details>
                        ) : null}
                        <JsonInspector label="payload_json (inputs)" raw={j.payload_json} />
                        <JsonInspector label="result_json (outputs / critic feedback)" raw={j.result_json} />
                        {j.celery_task_id && <p className="text-xs text-muted" style={{ margin: '4px 0 0 0' }}>celery: {j.celery_task_id}</p>}
                      </td>
                      <td>{new Date(j.created_at).toLocaleString()}</td>
                      <td>
                        {j.status === 'failed' && retryMap[j.job_type] && (
                          <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
                            onClick={() => runAction(`retry-job-${j.id}`, retryMap[j.job_type])}>
                            🔄 Retry
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === 'logs' && (
        <LogsPanel project={project} jobs={jobs} assets={assets} />
      )}

      {tab === 'eval' && (
        <EvalPanel project={project} scenes={scenes} />
      )}

      {tab === 'render' && (
        <div>
          <div className="mb-4">
            <StageJobPanel
              title="Stage 9 — Stitching (FFmpeg)"
              jobTypes={['stitching']}
              jobs={jobs}
              onRetry={() => api.stitch(projectId!).then(load)}
              retryDisabled={!!actionLoading}
            />
          </div>
          <div className="section-actions">
            <button className="btn btn-secondary btn-sm" disabled={!!actionLoading}
              onClick={() => runAction('stitch', () => api.stitch(projectId!))}>
              {actionLoading === 'stitch' ? '⏳ Stitching...' : '🧵 Run / Re-run Stitch'}
            </button>
            {(() => {
              const renderAsset = assets.find(a => a.asset_type === 'final_render')
              if (renderAsset?.status === 'failed') return (
                <span className="badge badge-failed">Stitch Failed — click to retry</span>
              )
              if (renderAsset?.status === 'generating' || renderAsset?.status === 'pending') return (
                <span className="badge badge-running">Stitching...</span>
              )
              return null
            })()}
          </div>
          {(() => {
            const finalRender = assets.find(a => a.asset_type === 'final_render' && a.status === 'complete')
            if (!finalRender) return (
              <div className="empty-state">
                <h3>No final render yet</h3>
                <p>Generate videos and audio, then click "Stitch" to create the final output.</p>
              </div>
            )
            return (
              <div className="card">
                <h3 className="card-title">🎥 Final Render</h3>
                <div className="mt-4">
                  <video controls style={{ width: '100%', maxHeight: 500, borderRadius: 'var(--radius-md)' }}>
                    <source src={assetUrl(finalRender)} type="video/mp4" />
                  </video>
                </div>
                <div className="flex gap-2 mt-4">
                  <a href={assetUrl(finalRender)} download className="btn btn-primary">
                    📥 Download MP4
                  </a>
                  <button className="btn btn-secondary" disabled={!!actionLoading}
                    onClick={() => runAction('stitch', () => api.stitch(projectId!))}>
                    🔄 Re-stitch
                  </button>
                </div>
              </div>
            )
          })()}
        </div>
      )}

      {/* Scene Detail Drawer */}
      {selectedScene && (
        <>
          <div className="drawer-overlay" onClick={() => setSelectedScene(null)} />
          <div className="drawer">
            <div className="drawer-header">
              <h2>Scene {selectedScene.order_index}</h2>
              <button className="drawer-close" onClick={() => setSelectedScene(null)}>✕</button>
            </div>
            <div className="flex items-center gap-2 mb-4">
              <StatusBadge status={selectedScene.status} />
              <span className="text-sm text-muted">{selectedScene.duration_seconds}s</span>
              {selectedScene.locked && <span>🔒 Locked</span>}
            </div>

            <ScenePromptDetail scene={selectedScene} characters={characters} locations={locations}
              onSaved={async () => {
                await load()
                try { setSelectedScene(await api.getScene(selectedScene.id)) } catch { /* drawer closed */ }
              }} />

            {(() => {
              const sv = assets.find(a => a.scene_id === selectedScene.id && a.asset_type === 'scene_video')
              return sv ? (
                <div className="form-group mt-4">
                  <label className="label">🎬 Scene Video Asset</label>
                  <p className="text-xs text-muted">
                    [{sv.status}] {sv.generation_provider || '—'} ·{' '}
                    {sv.file_path ? (
                      <a href={assetUrl(sv)} target="_blank" rel="noopener noreferrer"
                         style={{ wordBreak: 'break-all' }}>
                        {sv.file_path}
                      </a>
                    ) : '—'}
                  </p>
                  <JsonInspector label="metadata_json" raw={sv.metadata_json} />
                  <JsonInspector label="generation_params_json" raw={sv.generation_params_json} />
                </div>
              ) : null
            })()}

            <h2 className="section-title">🔒 Lock</h2>
            <div className="flex gap-2 mt-4">
              <button className="btn btn-secondary btn-sm"
                onClick={async () => {
                  await api.updateScene(selectedScene.id, { locked: !selectedScene.locked })
                  await load()
                  setSelectedScene(null)
                }}>
                {selectedScene.locked ? '🔓 Unlock' : '🔒 Lock'}
              </button>
              <button className="btn btn-primary btn-sm"
                onClick={async () => {
                  await api.regenerateScene(selectedScene.id)
                  setSelectedScene(null)
                  setTimeout(load, 1000)
                }}>
                🔄 Regenerate Video
              </button>
            </div>
          </div>{/* end drawer */}
        </>
      )}

      {/* ── Images Tab ─────────────────────────────────────────────── */}
      {tab === 'images' && (
        <div>
          <div className="flex-col gap-4 mb-4">
            <StageJobPanel
              title="Stage 6 — Image Pregeneration (SD 3.5)"
              jobTypes={['image_pregen']}
              jobs={jobs}
              onRetry={() => api.regenerateAllImages(projectId!).then(load)}
              retryDisabled={!!actionLoading}
            />
            <StillCriticAll jobs={jobs} />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
            <h2 className="section-title" style={{ margin: 0 }}>🎨 Generated Reference Images</h2>
            <button className="btn btn-secondary btn-sm" onClick={load}>↺ Refresh</button>
          </div>

          {!projectImages || (
            projectImages.characters.every(c => !c.image_url) &&
            projectImages.locations.every(l => !l.image_url) &&
            projectImages.scene_refs.every(s => !s.action_image_url && !s.action_image_2_url && (!s.action_image_seq_urls || s.action_image_seq_urls.length === 0))
          ) ? (
            <div className="empty-state">
              <p style={{ fontSize: '3rem', marginBottom: '1rem' }}>🖼️</p>
              <h3>No images generated yet</h3>
              <p className="text-muted" style={{ marginTop: '0.5rem' }}>
                Images are generated during the <strong>image_pregen</strong> stage using SD 3.5 Medium.
                Run the full pipeline to generate character portraits, backgrounds, and scene composites.
              </p>
              <p className="text-muted" style={{ fontSize: '0.8rem', marginTop: '0.5rem' }}>
                Project status: <strong>{project.status}</strong>
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2.5rem' }}>

              {/* Character Portraits */}
              {projectImages.characters.length > 0 && (
                <section>
                  <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem', color: 'var(--color-accent)' }}>
                    👤 Character Portraits
                  </h3>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '1rem' }}>
                    {projectImages.characters.map(char => (
                      <div key={char.id} style={{
                        background: 'var(--color-surface)',
                        borderRadius: '12px',
                        overflow: 'hidden',
                        border: '1px solid var(--color-border)',
                        transition: 'transform 0.2s, box-shadow 0.2s',
                      }}
                        onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.transform = 'translateY(-4px)'; (e.currentTarget as HTMLDivElement).style.boxShadow = '0 8px 24px rgba(0,0,0,0.3)' }}
                        onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.transform = ''; (e.currentTarget as HTMLDivElement).style.boxShadow = '' }}
                      >
                        {char.image_url ? (
                          <img
                            src={char.image_url}
                            alt={char.name}
                            style={{ width: '100%', aspectRatio: '3/4', objectFit: 'cover', display: 'block' }}
                            onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                          />
                        ) : (
                          <div style={{
                            width: '100%', aspectRatio: '3/4',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            background: 'var(--color-surface-2)', fontSize: '3rem',
                          }}>⏳</div>
                        )}
                        <div style={{ padding: '0.75rem' }}>
                          <p style={{ fontWeight: 600, marginBottom: '0.25rem' }}>{char.name}</p>
                          {char.physical_description && (
                            <p style={{ fontSize: '0.72rem', color: 'var(--color-muted)', lineHeight: 1.4, marginBottom: '0.25rem' }}>
                              {char.physical_description.slice(0, 80)}…
                            </p>
                          )}
                          <span style={{
                            display: 'inline-block', fontSize: '0.65rem', padding: '2px 8px',
                            borderRadius: '999px', marginTop: '0.25rem',
                            background: char.image_url ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)',
                            color: char.image_url ? '#10b981' : '#f59e0b',
                          }}>
                            {char.image_url ? '✓ Generated' : '⏳ Pending'}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Location Backgrounds */}
              {projectImages.locations.length > 0 && (
                <section>
                  <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem', color: 'var(--color-accent)' }}>
                    📍 Location Backgrounds
                  </h3>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1rem' }}>
                    {projectImages.locations.map(loc => (
                      <div key={loc.id} style={{
                        background: 'var(--color-surface)',
                        borderRadius: '12px',
                        overflow: 'hidden',
                        border: '1px solid var(--color-border)',
                        transition: 'transform 0.2s, box-shadow 0.2s',
                      }}
                        onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.transform = 'translateY(-4px)'; (e.currentTarget as HTMLDivElement).style.boxShadow = '0 8px 24px rgba(0,0,0,0.3)' }}
                        onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.transform = ''; (e.currentTarget as HTMLDivElement).style.boxShadow = '' }}
                      >
                        {loc.image_url ? (
                          <img
                            src={loc.image_url}
                            alt={loc.name}
                            style={{ width: '100%', aspectRatio: '16/9', objectFit: 'cover', display: 'block' }}
                            onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                          />
                        ) : (
                          <div style={{
                            width: '100%', aspectRatio: '16/9',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            background: 'var(--color-surface-2)', fontSize: '3rem',
                          }}>⏳</div>
                        )}
                        <div style={{ padding: '0.75rem' }}>
                          <p style={{ fontWeight: 600, marginBottom: '0.25rem' }}>{loc.name}</p>
                          {loc.description && (
                            <p style={{ fontSize: '0.72rem', color: 'var(--color-muted)', lineHeight: 1.4 }}>
                              {loc.description.slice(0, 100)}…
                            </p>
                          )}
                          <span style={{
                            display: 'inline-block', fontSize: '0.65rem', padding: '2px 8px',
                            borderRadius: '999px', marginTop: '0.5rem',
                            background: loc.image_url ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)',
                            color: loc.image_url ? '#10b981' : '#f59e0b',
                          }}>
                            {loc.image_url ? '✓ Generated' : '⏳ Pending'}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Scene Action Stills */}
              {projectImages.scene_refs.filter(s => s.action_image_url || s.action_image_2_url || (s.action_image_seq_urls && s.action_image_seq_urls.length > 0)).length > 0 && (
                <section>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
                    <h3 style={{ fontSize: '1.1rem', fontWeight: 600, margin: 0, color: 'var(--color-accent)' }}>
                      🎬 Scene Action Stills
                      <span style={{ fontSize: '0.75rem', color: 'var(--color-muted)', fontWeight: 400, marginLeft: '0.5rem' }}>
                        (per-second img2img sequence — used as LTX-Video conditioning)
                      </span>
                    </h3>
                    <button
                      className="btn btn-secondary btn-sm"
                      disabled={!!actionLoading}
                      onClick={() => {
                        if (window.confirm('Regenerate ALL action stills? This deletes existing files and re-runs SD3.5 image_pregen for every scene. The current images will be lost.')) {
                          runAction('regen-images', () => api.regenerateAllImages(projectId!), '🖼️ Force-regenerating all action stills...');
                        }
                      }}
                    >
                      {actionLoading === 'regen-images' ? '⏳ Running...' : '🔄 Regenerate All Images'}
                    </button>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {projectImages.scene_refs.map(ref => {
                      const seqItems = ref.action_image_seq || [];
                      const seqUrls = ref.action_image_seq_urls || [];
                      const hasAny = seqItems.length > 0 || seqUrls.length > 0 || ref.action_image_url || ref.action_image_2_url;
                      if (!hasAny) return null;
                      const items = seqItems.length > 0
                        ? seqItems
                        : (seqUrls.length > 0
                            ? seqUrls.map(u => ({ url: u, prompt: null, negative: null }))
                            : [ref.action_image_url, ref.action_image_2_url].filter(Boolean).map(u => ({ url: u as string, prompt: null, negative: null })));
                      return (
                        <div key={ref.id} style={{
                          background: 'var(--color-surface)',
                          borderRadius: '10px',
                          overflow: 'hidden',
                          border: '1px solid var(--color-border)',
                          padding: '0.75rem',
                        }}>
                          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                            <p style={{ fontWeight: 600, fontSize: '0.9rem', margin: 0 }}>
                              Scene {ref.order_index}
                              <span style={{ fontSize: '0.75rem', color: 'var(--color-muted)', fontWeight: 400, marginLeft: '0.5rem' }}>
                                {items.length} still{items.length === 1 ? '' : 's'}
                              </span>
                            </p>
                            {ref.visual_summary && (
                              <p style={{ fontSize: '0.7rem', color: 'var(--color-muted)', margin: 0, flex: 1, marginLeft: '1rem', textAlign: 'right' }}>
                                {ref.visual_summary.slice(0, 90)}…
                              </p>
                            )}
                          </div>
                          <div style={{ display: 'flex', gap: '12px', overflowX: 'auto', paddingBottom: '0.25rem' }}>
                            {items.map((it, i) => (
                              <div key={i} style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', gap: '4px', maxWidth: '260px' }}>
                                <div style={{ position: 'relative' }}>
                                  <img
                                    src={it.url}
                                    alt={`Scene ${ref.order_index} second ${i}`}
                                    style={{ width: '260px', aspectRatio: '3/4', objectFit: 'cover', display: 'block', borderRadius: '4px', background: '#222' }}
                                    onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                                  />
                                  <span style={{ position: 'absolute', bottom: 4, left: 4, background: 'rgba(0,0,0,0.7)', color: '#fff', fontSize: '0.65rem', padding: '1px 5px', borderRadius: '3px' }}>
                                    s{i}
                                  </span>
                                </div>
                                {it.prompt && (
                                  <details style={{ fontSize: '0.7rem', color: 'var(--color-muted)' }}>
                                    <summary style={{ cursor: 'pointer', color: 'var(--color-accent)', fontSize: '0.7rem' }}>prompt</summary>
                                    <p style={{ margin: '4px 0 0 0', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.3 }}>{it.prompt}</p>
                                    {it.negative && (
                                      <p style={{ margin: '4px 0 0 0', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.3, color: '#a55' }}>
                                        <strong>neg:</strong> {it.negative}
                                      </p>
                                    )}
                                  </details>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </section>
              )}

            </div>
          )}
        </div>
      )}
    </div>

    {/* ── Toast notifications ─────────────────────────────────────────── */}
    <div style={{
      position: 'fixed', bottom: '1.5rem', right: '1.5rem',
      display: 'flex', flexDirection: 'column', gap: '0.5rem', zIndex: 9999,
    }}>
      {toasts.map(t => (
        <div key={t.id} onClick={() => setToasts(ts => ts.filter(x => x.id !== t.id))} style={{
          padding: '0.75rem 1.25rem',
          borderRadius: '0.5rem',
          fontSize: '0.875rem',
          fontWeight: 500,
          cursor: 'pointer',
          maxWidth: '360px',
          boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
          animation: 'slideIn 0.2s ease',
          background: t.type === 'error' ? '#ef4444' : '#22c55e',
          color: '#fff',
        }}>
          {t.msg}
        </div>
      ))}
    </div>
    </>
  )
}

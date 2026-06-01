import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { StatusBadge } from './StatusBadge'
import { YouTubeMetadataModal } from './YouTubeMetadataModal'
import type { Asset, EpisodeListItem } from '../types'

interface Props {
  projectId: string
  selectedEpisodeId?: string | null
  onSelect?: (episodeId: string) => void
  onCreated?: () => void
  onDeleted?: () => void
}

const DURATIONS = [10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 271, 300, 304, 360]

const assetUrl = (asset: Asset) => {
  const name = asset.file_path?.split('/').pop()
  return name ? `/api/assets/${asset.id}/file/${name}` : `/api/assets/${asset.id}/file`
}

export function EpisodesPanel({ projectId, selectedEpisodeId, onSelect, onCreated, onDeleted }: Props) {
  const [episodes, setEpisodes] = useState<EpisodeListItem[]>([])
  const [assets, setAssets] = useState<Asset[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [rows, projectAssets] = await Promise.all([
        api.listEpisodes(projectId),
        api.listAssets(projectId),
      ])
      setEpisodes(rows)
      setAssets(projectAssets)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally { setLoading(false) }
  }, [projectId])

  useEffect(() => { load() }, [load])

  // Poll while any episode is non-terminal so the UI advances chips + finds finals.
  useEffect(() => {
    const active = episodes.some(e => e.status !== 'complete' && e.status !== 'failed')
    if (!active) return
    const t = window.setInterval(load, 5000)
    return () => window.clearInterval(t)
  }, [episodes, load])

  const finalAssetFor = (episodeId: string): Asset | undefined =>
    assets.find(a =>
      a.episode_id === episodeId && a.asset_type === 'final_render' && a.status === 'complete'
    )

  // When a YouTube URL is set, dress up the generic pipeline status with a
  // YouTube-specific label so the user knows the audio leg is the YT track.
  const youtubeStatusLabel = (ep: EpisodeListItem): string | undefined => {
    if (!ep.youtube_audio_url) return undefined
    switch (ep.status) {
      case 'audio_planning': return '🎵 Preparing YouTube audio…'
      case 'generating':     return '🎵 Downloading YouTube audio…'
      case 'stitching':      return '🎵 Overlaying YouTube audio…'
      case 'complete':       return '🎵 YouTube audio overlaid'
      default: return undefined
    }
  }

  const handleCreated = async () => {
    setShowModal(false)
    await load()
    onCreated?.()
  }

  const handleDelete = async (ep: EpisodeListItem) => {
    const label = `Episode ${ep.order_index}${ep.title ? ` — ${ep.title}` : ''}`
    if (!window.confirm(
      `Delete ${label}?\n\nThis removes the episode, its scenes, prompts, and rendered video. Project characters/locations stay.\n\nThis cannot be undone.`
    )) return
    try {
      await api.deleteEpisode(ep.id)
      await load()
      onDeleted?.()
    } catch (e: any) {
      window.alert(`Delete failed: ${e?.message || e}`)
    }
  }

  const [attaching, setAttaching] = useState<string | null>(null)
  const [ytMetaFor, setYtMetaFor] = useState<EpisodeListItem | null>(null)
  const handleAttachYoutube = async (ep: EpisodeListItem) => {
    const current = ep.youtube_audio_url || ''
    const url = window.prompt(
      `Paste a public YouTube URL to overlay on Episode ${ep.order_index}.`,
      current,
    )
    if (!url || !url.trim()) return
    const mix = window.confirm(
      `OK = MIX YouTube as background music UNDER existing audio (voiceover stays).\n` +
      `Cancel = REPLACE existing audio entirely with the YouTube track.`
    )
    setAttaching(ep.id)
    try {
      await api.attachYoutubeAudio(ep.id, url.trim(), mix ? 'mix' : 'replace')
      await load()
    } catch (e: any) {
      window.alert(`Attach failed: ${e?.message || e}`)
    } finally { setAttaching(null) }
  }

  if (loading) return <div className="panel">Loading episodes…</div>
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Episodes ({episodes.length})</h3>
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          + New episode
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {episodes.length === 0 ? (
        <div className="muted">No episodes yet. Click "+ New episode" to add one.</div>
      ) : (
        <div className="episodes-grid">
          {episodes.map(ep => {
            const finalAsset = finalAssetFor(ep.id)
            const isSelected = ep.id === selectedEpisodeId
            return (
              <div
                key={ep.id}
                className={`episode-card${isSelected ? ' episode-card-selected' : ''}`}
                onClick={() => onSelect?.(ep.id)}
                role={onSelect ? 'button' : undefined}
                tabIndex={onSelect ? 0 : undefined}
                title={onSelect ? 'Select this episode' : undefined}
              >
                <div className="episode-card-header">
                  <div className="episode-card-title">
                    <strong>Ep {ep.order_index}</strong>
                    <span className="episode-card-name">{ep.title}</span>
                  </div>
                  <div className="episode-card-actions">
                    {attaching === ep.id ? (
                      <StatusBadge
                        status="generating"
                        label="🎵 Downloading & overlaying YouTube audio…"
                        title="Stripping existing audio, downloading the YouTube track via yt-dlp, then running ffmpeg overlay."
                      />
                    ) : (
                      <StatusBadge
                        status={ep.status}
                        label={youtubeStatusLabel(ep)}
                        title={ep.youtube_audio_url || undefined}
                      />
                    )}
                    {finalAsset && (
                      <button
                        className="btn btn-sm"
                        onClick={(e) => { e.stopPropagation(); handleAttachYoutube(ep) }}
                        disabled={attaching === ep.id}
                        title={ep.youtube_audio_url
                          ? `Replace audio (current: ${ep.youtube_audio_url})`
                          : 'Attach YouTube audio (replaces existing audio)'}
                      >{attaching === ep.id ? '⏳' : '🎵'}</button>
                    )}
                    {finalAsset && (
                      <button
                        className="btn btn-sm"
                        onClick={(e) => { e.stopPropagation(); setYtMetaFor(ep) }}
                        title="Generate YouTube title + description to copy-paste"
                      >📋 YT</button>
                    )}
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={(e) => { e.stopPropagation(); handleDelete(ep) }}
                      title="Delete this episode (cannot be undone)"
                    >🗑️</button>
                  </div>
                </div>
                <div className="episode-card-meta">
                  <span>{ep.target_duration_seconds ? `${ep.target_duration_seconds}s` : '—'}</span>
                  <span>{ep.scene_count} scenes</span>
                  {ep.theme_hint && (
                    <span className="theme-cell" title={ep.theme_hint}>
                      🎬 {ep.theme_hint}
                    </span>
                  )}
                </div>
                {finalAsset ? (
                  <div className="episode-video" onClick={e => e.stopPropagation()}>
                    <video controls preload="metadata" playsInline>
                      <source src={assetUrl(finalAsset)} type="video/mp4" />
                    </video>
                    <a href={assetUrl(finalAsset)} download className="btn btn-sm">⬇ Download</a>
                    {attaching === ep.id && (
                      <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>
                        🎵 Downloading YouTube audio and overlaying… don't close the tab.
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="episode-video-placeholder muted">
                    {ep.status === 'failed'
                      ? '❌ Generation failed'
                      : ep.status === 'complete'
                        ? '⚠ Stitched output missing'
                        : youtubeStatusLabel(ep) ?? `⏳ ${ep.status.replace(/_/g, ' ')}…`}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
      {showModal && (
        <NewEpisodeModal
          projectId={projectId}
          hasPriorEpisodes={episodes.length > 0}
          onClose={() => setShowModal(false)}
          onCreated={handleCreated}
        />
      )}
      {ytMetaFor && (
        <YouTubeMetadataModal
          episode={ytMetaFor}
          onClose={() => setYtMetaFor(null)}
        />
      )}
    </div>
  )
}

interface ModalProps {
  projectId: string
  hasPriorEpisodes: boolean
  onClose: () => void
  onCreated: () => void
}

function NewEpisodeModal({ projectId, hasPriorEpisodes, onClose, onCreated }: ModalProps) {
  const [theme, setTheme] = useState('')
  const [duration, setDuration] = useState(30)
  const [showMore, setShowMore] = useState(false)
  const [title, setTitle] = useState('')
  const [continueFromPrev, setContinueFromPrev] = useState(hasPriorEpisodes)
  const [skipAudio, setSkipAudio] = useState(false)
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [youtubeAsBg, setYoutubeAsBg] = useState(false)
  const [storyText, setStoryText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    setError(null)
    setSubmitting(true)
    try {
      const hasStory = storyText.trim().length > 0
      const hasTheme = theme.trim().length > 0
      if (!hasStory && !hasTheme) {
        throw new Error('Provide a theme or full story text.')
      }
      const url = youtubeUrl.trim()
      await api.createEpisode(projectId, {
        title: title.trim() || undefined,
        theme_hint: hasStory ? undefined : theme.trim(),
        original_story_text: hasStory ? storyText.trim() : undefined,
        // Duration is derived from the YouTube clip when a URL is set.
        target_duration_seconds: url ? undefined : duration,
        continue_from_previous: continueFromPrev,
        skip_audio: skipAudio,
        youtube_audio_url: url || undefined,
        youtube_as_background_music: (url && youtubeAsBg) ? true : undefined,
      })
      onCreated()
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally { setSubmitting(false) }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h3>New episode</h3>
        <label className="field">
          <span>Theme</span>
          <textarea
            value={theme}
            onChange={e => setTheme(e.target.value)}
            placeholder="e.g. Tom corners Jerry under the kitchen sink with a vacuum and a soap-bottle ramp"
            rows={3}
          />
          <small className="muted">One-line idea. We'll expand it into a full story.</small>
        </label>
        <label className="field">
          <span>YouTube audio URL <span className="muted">(optional)</span></span>
          <input
            type="url"
            value={youtubeUrl}
            onChange={e => setYoutubeUrl(e.target.value)}
            placeholder="https://youtu.be/... — overlay this audio on the video"
          />
          <small className="muted">
            When set, the YouTube audio is downloaded + overlaid and the video
            length matches the clip's duration.
          </small>
        </label>
        {youtubeUrl.trim() && (
          <label className="field-inline">
            <input
              type="checkbox"
              checked={youtubeAsBg}
              onChange={e => setYoutubeAsBg(e.target.checked)}
            />
            <span>Mix YouTube as background music under narration (voiceover stays foreground)</span>
          </label>
        )}
        <label className="field">
          <span>Length{youtubeUrl.trim() ? ' (auto from YouTube)' : ''}</span>
          <select
            value={duration}
            onChange={e => setDuration(Number(e.target.value))}
            disabled={!!youtubeUrl.trim()}
          >
            {DURATIONS.map(d => <option key={d} value={d}>{d}s</option>)}
          </select>
        </label>
        <button className="link-button" onClick={() => setShowMore(s => !s)}>
          {showMore ? '▾ Hide advanced' : '▸ Show more'}
        </button>
        {showMore && (
          <div className="advanced">
            <label className="field">
              <span>Title (optional)</span>
              <input
                type="text" value={title} onChange={e => setTitle(e.target.value)}
                placeholder="auto-filled if blank"
              />
            </label>
            <label className="field-inline">
              <input
                type="checkbox" checked={continueFromPrev}
                disabled={!hasPriorEpisodes}
                onChange={e => setContinueFromPrev(e.target.checked)}
              />
              <span>Continue from previous episode (last frame chain)</span>
            </label>
            <label className="field-inline">
              <input
                type="checkbox" checked={skipAudio}
                onChange={e => setSkipAudio(e.target.checked)}
              />
              <span>Silent background video (skip narration — overlay your own audio later)</span>
            </label>
            <label className="field">
              <span>Full story text (optional — overrides theme)</span>
              <textarea
                value={storyText} onChange={e => setStoryText(e.target.value)}
                rows={5}
                placeholder="Paste a complete story here if you don't want to use the theme expander."
              />
            </label>
          </div>
        )}
        {error && <div className="error">{error}</div>}
        <div className="modal-actions">
          <button className="btn" onClick={onClose} disabled={submitting}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? 'Creating…' : 'Create episode ▶'}
          </button>
        </div>
      </div>
    </div>
  )
}

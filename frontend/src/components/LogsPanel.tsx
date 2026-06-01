import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { RenderJob, Asset, Project } from '../types'

interface Props {
  project: Project
  jobs: RenderJob[]
  assets: Asset[]
}

type Line = {
  ts: string
  level: 'queued' | 'running' | 'complete' | 'failed' | 'cancelled' | 'info'
  source: string
  detail?: string
  durMs?: number
  error?: string | null
}

const LEVEL_STYLE: Record<Line['level'], { icon: string; color: string }> = {
  queued:    { icon: '⏳', color: '#9ca3af' },
  running:   { icon: '▶',  color: '#38bdf8' },
  complete:  { icon: '✓',  color: '#22c55e' },
  failed:    { icon: '✗',  color: '#ef4444' },
  cancelled: { icon: '⊘',  color: '#9ca3af' },
  info:      { icon: '·',  color: '#a78bfa' },
}

const fmtDur = (ms?: number) => {
  if (!ms || ms < 1500) return ''
  return ms < 60_000 ? `${(ms / 1000).toFixed(1)}s` : `${(ms / 60_000).toFixed(1)}m`
}

const fmtTs = (iso: string) => {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour12: false }) + '.' +
    String(d.getMilliseconds()).padStart(3, '0')
}

const buildLines = (jobs: RenderJob[], assets: Asset[]): Line[] => {
  const lines: Line[] = []
  for (const j of jobs) {
    const durMs = new Date(j.updated_at).getTime() - new Date(j.created_at).getTime()
    lines.push({
      ts: j.created_at,
      level: j.status as Line['level'],
      source: j.job_type.replace(/_/g, ' '),
      detail: j.job_type_detail ?? undefined,
      durMs: ['complete', 'failed', 'cancelled'].includes(j.status) ? durMs : undefined,
      error: j.error_text,
    })
  }
  for (const a of assets) {
    if (a.status !== 'generating' && a.status !== 'failed') continue
    lines.push({
      ts: a.created_at,
      level: a.status === 'generating' ? 'running' : 'failed',
      source: `asset:${a.asset_type}`,
      detail: a.scene_id ? `scene:${a.scene_id.slice(0, 8)}` : undefined,
    })
  }
  lines.sort((x, y) => new Date(x.ts).getTime() - new Date(y.ts).getTime())
  return lines
}

export function LogsPanel({ project, jobs, assets }: Props) {
  const [autoScroll, setAutoScroll] = useState(true)
  const [filter, setFilter] = useState('')
  const [showCelery, setShowCelery] = useState(true)
  const [celeryLines, setCeleryLines] = useState<string[]>([])
  const [celeryErr, setCeleryErr] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const celeryEndRef = useRef<HTMLDivElement>(null)
  const lines = buildLines(jobs, assets)

  useEffect(() => {
    if (!showCelery) return
    let cancelled = false
    const fetchTail = async () => {
      try {
        const r = await api.getProjectCeleryLog(project.id, 300)
        if (!cancelled) { setCeleryLines(r.lines); setCeleryErr(null) }
      } catch (e: any) {
        if (!cancelled) setCeleryErr(e?.message || String(e))
      }
    }
    fetchTail()
    const t = setInterval(fetchTail, 3000)
    return () => { cancelled = true; clearInterval(t) }
  }, [showCelery, project.id])

  useEffect(() => {
    if (autoScroll) celeryEndRef.current?.scrollIntoView({ block: 'end' })
  }, [celeryLines.length, autoScroll])
  const visible = filter
    ? lines.filter(l => (l.source + ' ' + (l.detail || '') + ' ' + (l.error || '')).toLowerCase().includes(filter.toLowerCase()))
    : lines

  useEffect(() => {
    if (autoScroll) endRef.current?.scrollIntoView({ block: 'end' })
  }, [visible.length, autoScroll])

  const running = jobs.filter(j => j.status === 'running' || j.status === 'queued')

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px',
        background: 'var(--color-surface-2, #0f172a)', borderBottom: '1px solid var(--color-border, #1f2937)',
        flexWrap: 'wrap',
      }}>
        <strong style={{ fontSize: '0.85rem' }}>📜 Project logs</strong>
        <span className="text-xs text-muted">project:{project.id.slice(0, 8)} · status:{project.status}</span>
        {running.length > 0 && (
          <span className="text-xs" style={{ color: '#38bdf8' }}>
            ▶ {running.map(j => j.job_type.replace(/_/g, ' ')).join(', ')}
          </span>
        )}
        <div style={{ flex: 1 }} />
        <input
          type="search" placeholder="filter…" value={filter}
          onChange={e => setFilter(e.target.value)}
          style={{ fontSize: '0.75rem', padding: '2px 6px', minWidth: 120 }}
        />
        <label className="text-xs text-muted" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)} />
          auto-scroll
        </label>
        <span className="text-xs text-muted">{visible.length}/{lines.length} lines</span>
      </div>
      <div style={{
        maxHeight: 520, overflowY: 'auto', padding: '8px 12px',
        background: '#0b1020', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        fontSize: '0.78rem', lineHeight: 1.55,
      }}>
        {visible.length === 0 ? (
          <p className="text-xs text-muted">No log lines yet — kick off a pipeline stage.</p>
        ) : visible.map((l, i) => {
          const s = LEVEL_STYLE[l.level] || LEVEL_STYLE.info
          return (
            <div key={i} style={{ color: '#d1d5db', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              <span style={{ color: '#6b7280' }}>{fmtTs(l.ts)}</span>
              {'  '}
              <span style={{ color: s.color }}>{s.icon} {l.level.toUpperCase().padEnd(8)}</span>
              {' '}
              <span style={{ color: '#e5e7eb' }}>{l.source}</span>
              {l.detail && <span style={{ color: '#9ca3af' }}>  · {l.detail}</span>}
              {l.durMs ? <span style={{ color: '#6b7280' }}>  ⏱ {fmtDur(l.durMs)}</span> : null}
              {l.error && (
                <div style={{ color: '#fca5a5', marginLeft: 24 }}>
                  ↳ {l.error.length > 240 ? l.error.slice(0, 240) + '…' : l.error}
                </div>
              )}
            </div>
          )
        })}
        <div ref={endRef} />
      </div>

      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px',
        background: 'var(--color-surface-2, #0f172a)',
        borderTop: '1px solid var(--color-border, #1f2937)',
        borderBottom: showCelery ? '1px solid var(--color-border, #1f2937)' : 'none',
      }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
          <input type="checkbox" checked={showCelery} onChange={e => setShowCelery(e.target.checked)} />
          <strong style={{ fontSize: '0.85rem' }}>🔧 Raw celery worker (project-filtered)</strong>
        </label>
        <span className="text-xs text-muted">{celeryLines.length} lines · polls 3s</span>
        {celeryErr && <span className="text-xs" style={{ color: '#ef4444' }}>err: {celeryErr}</span>}
      </div>
      {showCelery && (
        <div style={{
          maxHeight: 420, overflowY: 'auto', padding: '8px 12px',
          background: '#000', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
          fontSize: '0.72rem', lineHeight: 1.5, color: '#cbd5e1',
        }}>
          {celeryLines.length === 0 ? (
            <p className="text-xs text-muted">
              No celery lines mention this project yet. Lines must contain the project UUID — many do
              (file paths under storage/.../{project.id.slice(0, 8)}…).
            </p>
          ) : celeryLines.map((line, i) => {
            const isErr = /ERROR|Traceback|FAIL|: error\b/i.test(line)
            const isWarn = /WARNING|WARN\b/.test(line)
            const color = isErr ? '#fca5a5' : isWarn ? '#fde68a' : '#cbd5e1'
            return (
              <div key={i} style={{ color, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {line}
              </div>
            )
          })}
          <div ref={celeryEndRef} />
        </div>
      )}
    </div>
  )
}

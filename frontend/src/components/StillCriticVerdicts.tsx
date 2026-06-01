import type { RenderJob } from '../types'

interface Verdict {
  approved?: boolean
  shows_action?: boolean
  subject_visible?: boolean
  composition_issues?: string[]
  anatomy_issues?: string[]
  burned_in_text?: boolean
  summary?: string
}

interface StillIssue {
  scene_index?: number
  still?: string
  verdict?: Verdict
}

function pickStillCritic(jobs: RenderJob[]): StillIssue[] {
  const j = jobs
    .filter(x => x.job_type === 'image_pregen' && x.result_json)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0]
  if (!j?.result_json) return []
  try {
    const r = JSON.parse(j.result_json)
    return (r?.still_critic?.issues || []) as StillIssue[]
  } catch { return [] }
}

export function StillCriticForScene({ jobs, sceneIndex }: { jobs: RenderJob[]; sceneIndex: number }) {
  const issues = pickStillCritic(jobs).filter(i => i.scene_index === sceneIndex)
  if (issues.length === 0) return null
  return (
    <div style={{ marginTop: 6, padding: 6, borderRadius: 4, background: 'rgba(245,158,11,0.08)' }}>
      <p style={{ fontSize: '0.7rem', color: '#f59e0b', margin: 0, fontWeight: 600 }}>
        ⚠️ Still-critic flagged {issues.length} still{issues.length === 1 ? '' : 's'}
      </p>
      {issues.map((i, k) => {
        const v = i.verdict || {}
        const flags = [
          ...(v.composition_issues || []),
          ...(v.anatomy_issues || []),
          v.burned_in_text ? 'burned-in text' : null,
          v.shows_action === false ? 'action not visible' : null,
          v.subject_visible === false ? 'subject not visible' : null,
        ].filter(Boolean)
        return (
          <p key={k} style={{ fontSize: '0.7rem', color: 'var(--color-muted)', margin: '2px 0 0 0' }}>
            <span style={{ color: 'var(--text-secondary)' }}>{(i.still || '').split('/').pop()}:</span>{' '}
            {flags.join(', ') || v.summary || '(no detail)'}
          </p>
        )
      })}
    </div>
  )
}

export function StillCriticAll({ jobs }: { jobs: RenderJob[] }) {
  const issues = pickStillCritic(jobs)
  if (issues.length === 0) return null
  const byScene = new Map<number, StillIssue[]>()
  for (const i of issues) {
    const k = i.scene_index ?? -1
    if (!byScene.has(k)) byScene.set(k, [])
    byScene.get(k)!.push(i)
  }
  return (
    <div className="card" style={{ borderLeft: '3px solid #f59e0b' }}>
      <h3 className="card-title">🔍 Still-Critic Verdicts <span style={{ fontSize: '0.7rem', fontWeight: 400, color: 'var(--color-muted)' }}>(observational, non-blocking)</span></h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
        {[...byScene.entries()].sort(([a], [b]) => a - b).map(([si, list]) => (
          <div key={si} style={{ padding: 8, borderRadius: 6, background: 'var(--color-surface-2,#111)' }}>
            <strong style={{ fontSize: '0.8rem' }}>Scene {si + 1}</strong>
            {list.map((i, k) => {
              const v = i.verdict || {}
              return (
                <div key={k} style={{ marginTop: 4, fontSize: '0.72rem', color: 'var(--color-muted)' }}>
                  <p style={{ margin: 0 }}>
                    <strong>{(i.still || '').split('/').pop()}</strong>{' '}
                    <span style={{ color: v.approved ? '#10b981' : '#ef4444' }}>
                      {v.approved ? '✓' : '✗'}
                    </span>
                  </p>
                  {v.summary && <p style={{ margin: '2px 0 0 0' }}>{v.summary}</p>}
                  {(v.composition_issues?.length || v.anatomy_issues?.length) ? (
                    <p style={{ margin: '2px 0 0 0' }}>
                      flags: {[...(v.composition_issues || []), ...(v.anatomy_issues || [])].join(', ')}
                    </p>
                  ) : null}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

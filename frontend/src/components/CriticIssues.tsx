import type { RenderJob } from '../types'
import { Collapsible } from './Collapsible'

interface Issue {
  scene_index?: number
  issue_type?: string
  description?: string
  severity?: 'low' | 'medium' | 'high' | string
}

interface CriticReview {
  overall_quality?: string
  approved?: boolean
  suggestions?: string[]
  issues?: Issue[]
}

const sevColor = (s?: string) =>
  s === 'high' ? '#ef4444'
  : s === 'medium' ? '#f59e0b'
  : s === 'low' ? '#10b981'
  : 'var(--color-muted)'

function pickReview(jobs: RenderJob[]): CriticReview | null {
  const j = jobs
    .filter(x => x.job_type === 'consistency_review' && x.result_json)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0]
  if (!j?.result_json) return null
  try { return JSON.parse(j.result_json) as CriticReview } catch { return null }
}

/** Compact per-scene critic issue list (filtered by scene_index). */
export function SceneCriticIssues({ jobs, sceneIndex }: { jobs: RenderJob[]; sceneIndex: number }) {
  const review = pickReview(jobs)
  if (!review) return null
  const issues = (review.issues || []).filter(i => i.scene_index === sceneIndex)
  if (issues.length === 0) return null
  return (
    <div style={{ marginTop: 6, padding: 6, borderRadius: 4, background: 'rgba(239,68,68,0.08)' }}>
      <p style={{ fontSize: '0.7rem', color: '#ef4444', margin: 0, fontWeight: 600 }}>
        ⚠️ {issues.length} critic issue{issues.length === 1 ? '' : 's'}
      </p>
      {issues.map((i, k) => (
        <p key={k} style={{ fontSize: '0.7rem', color: 'var(--color-muted)', margin: '2px 0 0 0' }}>
          <span style={{ color: sevColor(i.severity), fontWeight: 600 }}>[{i.severity}]</span>{' '}
          <span style={{ color: 'var(--text-secondary)' }}>{i.issue_type}:</span>{' '}
          {i.description}
        </p>
      ))}
    </div>
  )
}

/** Full critic review block for the Scenes tab. */
export function CriticReviewSummary({ jobs }: { jobs: RenderJob[] }) {
  const review = pickReview(jobs)
  if (!review) return null
  const issuesByScene = new Map<number, Issue[]>()
  for (const i of review.issues || []) {
    const k = i.scene_index ?? -1
    if (!issuesByScene.has(k)) issuesByScene.set(k, [])
    issuesByScene.get(k)!.push(i)
  }
  const title = (
    <>
      <span>🔍 Consistency Critic</span>
      <span style={{ fontSize: '0.75rem', fontWeight: 400,
        color: review.approved ? '#10b981' : '#f59e0b' }}>
        {review.approved ? '✓ approved' : `needs revision · ${review.overall_quality || '?'}`}
      </span>
    </>
  )
  return (
    <Collapsible title={title}>
      {(review.issues?.length ?? 0) === 0 ? (
        <p className="text-xs text-muted" style={{ marginTop: 6 }}>No issues raised.</p>
      ) : (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[...issuesByScene.entries()].sort(([a], [b]) => a - b).map(([si, list]) => (
            <div key={si} style={{ padding: 8, borderRadius: 6, background: 'var(--color-surface-2,#111)' }}>
              <strong style={{ fontSize: '0.8rem' }}>
                {si >= 0 ? `Scene ${si}` : 'Project-level'}
              </strong>
              {list.map((i, k) => (
                <p key={k} style={{ fontSize: '0.75rem', color: 'var(--color-muted)', margin: '4px 0 0 0' }}>
                  <span style={{ color: sevColor(i.severity), fontWeight: 600 }}>[{i.severity}]</span>{' '}
                  <span style={{ color: 'var(--text-secondary)' }}>{i.issue_type}:</span>{' '}
                  {i.description}
                </p>
              ))}
            </div>
          ))}
        </div>
      )}
      {review.suggestions && review.suggestions.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <p style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', margin: 0 }}>Suggestions</p>
          <ul style={{ margin: '4px 0 0 0', paddingLeft: 18, color: 'var(--color-muted)', fontSize: '0.75rem' }}>
            {review.suggestions.map((s, k) => <li key={k}>{s}</li>)}
          </ul>
        </div>
      )}
    </Collapsible>
  )
}

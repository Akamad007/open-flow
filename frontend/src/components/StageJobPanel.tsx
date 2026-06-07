import { StatusBadge } from './StatusBadge'
import { JsonInspector } from './JsonInspector'
import { Collapsible } from './Collapsible'
import type { RenderJob, JobType } from '../types'

interface Props {
  title: string
  /** Job types this stage owns (e.g. ['story_analysis']) */
  jobTypes: JobType[]
  jobs: RenderJob[]
  onRetry?: (jobType: JobType) => void
  retryDisabled?: boolean
}

const formatDur = (created: string, updated: string) => {
  const ms = new Date(updated).getTime() - new Date(created).getTime()
  return ms > 1500 ? `${(ms / 1000).toFixed(1)}s` : null
}

export function StageJobPanel({ title, jobTypes, jobs, onRetry, retryDisabled }: Props) {
  const stageJobs = jobs
    .filter(j => jobTypes.includes(j.job_type))
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())

  const latest = stageJobs[stageJobs.length - 1]
  const summary = (
    <>
      <span>{title}</span>
      {latest
        ? <StatusBadge status={latest.status} />
        : <span className="text-xs text-muted">not run</span>}
    </>
  )

  return (
    <Collapsible title={summary}>
      {stageJobs.length === 0 ? (
        <p className="text-xs text-muted">No job has run for this stage yet.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {stageJobs.map(j => {
            const dur = formatDur(j.created_at, j.updated_at)
            return (
              <div key={j.id} style={{ padding: 8, borderRadius: 6, background: 'var(--color-surface-2, #111)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <strong style={{ fontSize: '0.8rem' }}>{j.job_type.replace(/_/g, ' ')}</strong>
                  {j.job_type_detail && <span className="text-xs text-muted">· {j.job_type_detail}</span>}
                  <StatusBadge status={j.status} />
                  {dur && <span className="text-xs text-muted">⏱️ {dur}</span>}
                  <span className="text-xs text-muted">{new Date(j.created_at).toLocaleString()}</span>
                  {j.status === 'failed' && onRetry && (
                    <button className="btn btn-secondary btn-sm" disabled={retryDisabled}
                      onClick={() => onRetry(j.job_type)}>🔄 Retry</button>
                  )}
                </div>
                {j.error_text && (
                  <details style={{ marginTop: 6 }}>
                    <summary className="error-summary">
                      {j.error_text.substring(0, 100)}{j.error_text.length > 100 ? '…' : ''}
                    </summary>
                    <pre className="error-detail">{j.error_text}</pre>
                  </details>
                )}
                <JsonInspector label="payload_json (inputs)" raw={j.payload_json} />
                <JsonInspector label="result_json (outputs / critic feedback)" raw={j.result_json} />
              </div>
            )
          })}
        </div>
      )}
    </Collapsible>
  )
}

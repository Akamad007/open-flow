import type { Project, Scene, EvaluationResult } from '../types'

interface Props { project: Project; scenes: Scene[] }

const parse = (raw: string | null): EvaluationResult | null => {
  if (!raw) return null
  try { return JSON.parse(raw) as EvaluationResult } catch { return null }
}

const fmt = (n: number | undefined, digits = 3) =>
  n === undefined || Number.isNaN(n) ? '—' : n.toFixed(digits)

const verdictColor = (v: string): string => {
  if (/weak|jittery|static|frantic/.test(v)) return '#fca5a5'
  if (/strong/.test(v)) return '#86efac'
  return '#cbd5e1'
}

function EvalCard({ title, subtitle, result }: {
  title: string; subtitle?: string; result: EvaluationResult | null
}) {
  if (!result) {
    return (
      <div className="card" style={{ borderLeft: '3px solid var(--color-muted)' }}>
        <h4 style={{ margin: 0 }}>{title}</h4>
        {subtitle && <p className="text-xs text-muted" style={{ marginTop: 4 }}>{subtitle}</p>}
        <p className="text-xs text-muted" style={{ marginTop: 6 }}>No evaluation yet.</p>
      </div>
    )
  }
  if (result.error) {
    return (
      <div className="card" style={{ borderLeft: '3px solid #ef4444' }}>
        <h4 style={{ margin: 0 }}>{title}</h4>
        <pre className="error-detail" style={{ marginTop: 8 }}>{result.error}</pre>
      </div>
    )
  }
  const m = result.metrics
  const s = result.suggestion
  return (
    <div className="card" style={{ borderLeft: '3px solid var(--color-accent, #38bdf8)' }}>
      <h4 style={{ margin: 0 }}>{title}</h4>
      {subtitle && <p className="text-xs text-muted" style={{ marginTop: 4 }}>{subtitle}</p>}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8, marginTop: 10 }}>
        {m?.clip && (
          <div><div className="text-xs text-muted">CLIP prompt</div>
            <div>mean {fmt(m.clip.mean)} · min {fmt(m.clip.min)}</div></div>
        )}
        {m?.identity && (
          <div><div className="text-xs text-muted">Identity</div>
            <div>mean {fmt(m.identity.mean)} · face hit {fmt(m.identity.frames_with_face * 100, 0)}%</div></div>
        )}
        {m?.motion && (
          <div><div className="text-xs text-muted">Motion</div>
            <div>{fmt(m.motion.mean_flow_mag, 2)} px/frame</div></div>
        )}
        {m?.smoothness && (
          <div><div className="text-xs text-muted">Smoothness</div>
            <div>{fmt(m.smoothness.mean_ssim)}</div></div>
        )}
      </div>

      {m?.verdict && m.verdict.length > 0 && (
        <ul style={{ marginTop: 10, paddingLeft: 18, fontSize: '0.8rem' }}>
          {m.verdict.map((v, i) => (
            <li key={i} style={{ color: verdictColor(v) }}>{v}</li>
          ))}
        </ul>
      )}

      {s && s.deltas && Object.keys(s.deltas).length > 0 && (
        <div style={{ marginTop: 10, padding: 8, background: 'rgba(56,189,248,0.08)', borderRadius: 6 }}>
          <strong style={{ fontSize: '0.8rem' }}>Suggested lever changes</strong>
          <ul style={{ marginTop: 4, paddingLeft: 18, fontSize: '0.8rem' }}>
            {s.reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
          <pre style={{ fontSize: '0.72rem', marginTop: 6 }}>{JSON.stringify(s.deltas, null, 2)}</pre>
        </div>
      )}

      {s && (!s.deltas || Object.keys(s.deltas).length === 0) && (
        <p className="text-xs" style={{ color: '#86efac', marginTop: 8 }}>✓ All metrics within target — no lever changes suggested.</p>
      )}
    </div>
  )
}

export function EvalPanel({ project, scenes }: Props) {
  const finalRes = parse(project.final_evaluation_json)
  const sceneEvals = scenes
    .map(s => ({ scene: s, res: parse(s.evaluation_json) }))
    .filter(x => x.res !== null)

  if (!finalRes && sceneEvals.length === 0) {
    return (
      <div className="empty-state">
        <h3>📊 No evaluations yet</h3>
        <p className="text-xs text-muted">
          Per-scene and final-render evaluations run automatically after stitching completes
          (CLIP prompt adherence, identity vs portrait, motion magnitude, temporal smoothness).
        </p>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <EvalCard
        title="🎥 Final render"
        subtitle="Stitched output — motion / smoothness across the whole video"
        result={finalRes}
      />
      <h3 style={{ margin: '6px 0 0 0', fontSize: '0.9rem' }}>Per-scene</h3>
      {sceneEvals.length === 0 ? (
        <p className="text-xs text-muted">No per-scene evaluations stored yet.</p>
      ) : sceneEvals.map(({ scene, res }) => (
        <EvalCard
          key={scene.id}
          title={`Scene ${scene.order_index}`}
          subtitle={scene.visual_summary || scene.scene_purpose || scene.id.slice(0, 8)}
          result={res}
        />
      ))}
    </div>
  )
}

import type { Project } from '../types'

interface Beat {
  beat_index?: number
  description?: string
  characters?: string[]
  location?: string
  estimated_duration?: number
  [key: string]: unknown
}

function parseBeats(raw: string | null): Beat[] | null {
  if (!raw) return null
  try {
    const v = JSON.parse(raw)
    return Array.isArray(v) ? v : null
  } catch { return null }
}

export function StoryAnalysis({ project }: { project: Project }) {
  const beats = parseBeats(project.beat_list_json)
  const hasAny = project.story_summary || project.style_lock || project.pacing_notes || beats
  if (!hasAny) return null

  return (
    <div className="flex-col gap-4 mt-4">
      {project.story_summary && (
        <div className="card">
          <h3 className="card-title">📊 Summary</h3>
          <p className="text-sm" style={{ color: 'var(--text-secondary)', marginTop: 8 }}>
            {project.story_summary}
          </p>
        </div>
      )}
      {project.style_lock && (
        <div className="card">
          <h3 className="card-title">🎨 Style Lock <span style={{ fontSize: '0.7rem', color: 'var(--color-muted)', fontWeight: 400 }}>
            (embedded verbatim into every scene prompt)
          </span></h3>
          <p className="text-sm" style={{ color: 'var(--text-accent, #facc15)', marginTop: 8, fontStyle: 'italic' }}>
            "{project.style_lock}"
          </p>
        </div>
      )}
      {project.pacing_notes && (
        <div className="card">
          <h3 className="card-title">⏱️ Pacing Notes</h3>
          <p className="text-sm" style={{ color: 'var(--text-secondary)', marginTop: 8, whiteSpace: 'pre-wrap' }}>
            {project.pacing_notes}
          </p>
        </div>
      )}
      {beats && beats.length > 0 && (
        <div className="card">
          <h3 className="card-title">🎯 Beats ({beats.length})</h3>
          <ol style={{ paddingLeft: 20, marginTop: 8 }}>
            {beats.map((b, i) => (
              <li key={i} style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: 6 }}>
                <strong>{b.description || JSON.stringify(b)}</strong>
                {(b.characters?.length || b.location || b.estimated_duration) && (
                  <div style={{ fontSize: '0.7rem', color: 'var(--color-muted)', marginTop: 2 }}>
                    {b.characters?.length ? <>👤 {b.characters.join(', ')} · </> : null}
                    {b.location ? <>📍 {b.location} · </> : null}
                    {b.estimated_duration ? <>⏱️ {b.estimated_duration}s</> : null}
                  </div>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

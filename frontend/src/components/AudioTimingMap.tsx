interface Segment {
  scene_index?: number
  audio_segment_start?: number
  audio_segment_end?: number
  narration_excerpt?: string
  transition_note?: string
  [key: string]: unknown
}

function parseMap(raw: string | null): Segment[] | null {
  if (!raw) return null
  try {
    const v = JSON.parse(raw)
    return Array.isArray(v) ? v : null
  } catch { return null }
}

export function AudioTimingMap({ raw }: { raw: string | null }) {
  const segs = parseMap(raw)
  if (!segs || segs.length === 0) return null
  return (
    <div className="card">
      <h3 className="card-title">🗺️ Timing Map (per-scene narration)</h3>
      <table style={{ width: '100%', fontSize: '0.8rem', marginTop: 8 }}>
        <thead>
          <tr style={{ textAlign: 'left', color: 'var(--color-muted)' }}>
            <th style={{ padding: '4px 8px' }}>Scene</th>
            <th style={{ padding: '4px 8px' }}>Window</th>
            <th style={{ padding: '4px 8px' }}>Narration</th>
            <th style={{ padding: '4px 8px' }}>Transition</th>
          </tr>
        </thead>
        <tbody>
          {segs.map((s, i) => (
            <tr key={i} style={{ borderTop: '1px solid var(--color-border)' }}>
              <td style={{ padding: '6px 8px', verticalAlign: 'top' }}>
                {(s.scene_index ?? i) + 1}
              </td>
              <td style={{ padding: '6px 8px', verticalAlign: 'top', whiteSpace: 'nowrap' }}>
                {s.audio_segment_start != null ? s.audio_segment_start.toFixed(1) : '?'}s
                {' – '}
                {s.audio_segment_end != null ? s.audio_segment_end.toFixed(1) : '?'}s
              </td>
              <td style={{ padding: '6px 8px', color: 'var(--text-secondary)' }}>
                {s.narration_excerpt || '—'}
              </td>
              <td style={{ padding: '6px 8px', color: 'var(--color-muted)' }}>
                {s.transition_note || '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

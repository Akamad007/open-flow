interface Props {
  label?: string
  raw: string | null | undefined
  /** When true, opens by default */
  open?: boolean
}

export function JsonInspector({ label = 'JSON', raw, open = false }: Props) {
  if (!raw) return null
  let pretty = raw
  try { pretty = JSON.stringify(JSON.parse(raw), null, 2) } catch { /* keep raw */ }
  return (
    <details open={open} style={{ marginTop: 6 }}>
      <summary style={{ cursor: 'pointer', fontSize: '0.75rem', color: 'var(--color-accent)' }}>
        {label}
      </summary>
      <pre style={{
        margin: '6px 0 0 0',
        padding: '0.5rem',
        background: 'var(--color-surface-2, #111)',
        borderRadius: 6,
        fontSize: '0.7rem',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        maxHeight: 360,
        overflow: 'auto',
      }}>{pretty}</pre>
    </details>
  )
}

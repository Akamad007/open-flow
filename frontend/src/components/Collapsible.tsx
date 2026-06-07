import type { ReactNode } from 'react'

interface Props {
  title: ReactNode
  defaultOpen?: boolean
  children: ReactNode
}

export function Collapsible({ title, defaultOpen = false, children }: Props) {
  return (
    <details className="collapsible" open={defaultOpen}>
      <summary className="collapsible-summary"><span className="collapsible-title">{title}</span></summary>
      <div className="collapsible-body">{children}</div>
    </details>
  )
}

interface Props {
  status: string
  label?: string
  title?: string
}

export function StatusBadge({ status, label, title }: Props) {
  return (
    <span className={`badge badge-${status}`} title={title}>
      {label ?? status.replace(/_/g, ' ')}
    </span>
  )
}

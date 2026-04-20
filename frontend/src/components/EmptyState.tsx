type EmptyStateProps = {
  title: string
  description?: string
}

export function EmptyState({ title, description }: EmptyStateProps) {
  return (
    <div className="empty-state" role="note">
      <strong>{title}</strong>
      {description ? <p>{description}</p> : null}
    </div>
  )
}

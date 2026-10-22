import type { CameraSummary } from '@caelum/api-client'

export interface CameraCardProps {
  camera: CameraSummary
  /** Fully-resolved thumbnail URL (already run through the remote client's
   * `resolveUrl`) — `null` when the camera has no frames yet. */
  thumbnailUrl: string | null
  updatedAt?: string
  onClick?: () => void
  className?: string
}

export function CameraCard({ camera, thumbnailUrl, updatedAt, onClick, className }: CameraCardProps) {
  const Wrapper = onClick ? 'button' : 'div'
  return (
    <Wrapper
      onClick={onClick}
      className={[
        'group flex flex-col overflow-hidden border border-border bg-panel text-left transition rounded-md',
        onClick ? 'cursor-pointer hover:border-sky' : '',
        className ?? '',
      ].join(' ')}
    >
      <div className="aspect-video w-full overflow-hidden bg-surface-0">
        {thumbnailUrl ? (
          <img
            src={thumbnailUrl}
            alt={camera.name}
            className="h-full w-full object-cover transition group-hover:scale-[1.02]"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-xs text-ink-muted">
            No frames yet
          </div>
        )}
      </div>
      <div className="flex flex-col gap-0.5 border-t border-border-subtle px-4 py-3">
        <span className="font-medium text-ink">{camera.name}</span>
        <span className="font-mono text-xs text-ink-muted">{camera.slug}</span>
        {updatedAt ? <span className="text-xs text-ink-muted">Updated {updatedAt}</span> : null}
      </div>
    </Wrapper>
  )
}

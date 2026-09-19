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
        'group flex flex-col overflow-hidden rounded-lg border border-slate-800 bg-slate-900/60 text-left transition',
        onClick ? 'cursor-pointer hover:border-slate-600 hover:bg-slate-900' : '',
        className ?? '',
      ].join(' ')}
    >
      <div className="aspect-video w-full overflow-hidden bg-slate-950">
        {thumbnailUrl ? (
          <img
            src={thumbnailUrl}
            alt={camera.name}
            className="h-full w-full object-cover transition group-hover:scale-[1.02]"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-xs text-slate-600">
            No frames yet
          </div>
        )}
      </div>
      <div className="flex flex-col gap-0.5 px-4 py-3">
        <span className="font-medium text-slate-100">{camera.name}</span>
        <span className="text-xs text-slate-500">{camera.slug}</span>
        {updatedAt ? <span className="text-xs text-slate-500">Updated {updatedAt}</span> : null}
      </div>
    </Wrapper>
  )
}

import { useState } from 'react'

export interface KeogramStripProps {
  src: string
  date: string
  caption?: string
  className?: string
}

/**
 * A daily keogram image with a caption. The backend only produces
 * `<slug>/derivatives/<date>/keogram.png` once there's a night's worth of
 * frames for that date, so a 404 here is normal and expected, not an
 * error — render a quiet placeholder instead of a broken image icon.
 */
export function KeogramStrip({ src, date, caption, className }: KeogramStripProps) {
  const [failed, setFailed] = useState(false)

  return (
    <figure className={['flex flex-col gap-2', className ?? ''].join(' ')}>
      {failed ? (
        <div className="flex h-24 w-full items-center justify-center border border-line-soft bg-panel text-xs text-ink-faint">
          No keogram available for {date}
        </div>
      ) : (
        <img
          src={src}
          alt={`Keogram for ${date}`}
          className="w-full border border-line-soft bg-void"
          onError={() => setFailed(true)}
        />
      )}
      <figcaption className="font-mono text-xs text-ink-faint">{caption ?? `Keogram · ${date}`}</figcaption>
    </figure>
  )
}

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
        <div className="flex h-24 w-full items-center justify-center rounded bg-slate-900/60 text-xs text-slate-500">
          No keogram available for {date}
        </div>
      ) : (
        <img
          src={src}
          alt={`Keogram for ${date}`}
          className="w-full rounded bg-slate-950"
          onError={() => setFailed(true)}
        />
      )}
      <figcaption className="text-xs text-slate-500">{caption ?? `Keogram · ${date}`}</figcaption>
    </figure>
  )
}

import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { SkyObject } from '@caelum/api-client'
import { compassPoint } from '@roman-dvorak/caelum-sky'

const HIT_RADIUS_PX = 14

function describe(object: SkyObject): string {
  const where = `alt ${object.alt_deg.toFixed(1)}° · az ${object.az_deg.toFixed(0)}° ${compassPoint(object.az_deg)}`
  return object.kind === 'star' ? `${object.name} · mag ${object.mag.toFixed(1)} · ${where}` : `${object.name} · ${where}`
}

/**
 * Wraps an image box and shows a popup naming the star, planet, Sun or Moon
 * under the pointer. The objects arrive already projected onto the frame (as
 * fractions of its size), so this only has to find the nearest one — it works
 * on any view that shows the full frame in a box of its own aspect ratio.
 */
export function SkyHover({ objects, children }: { objects: SkyObject[]; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<{ object: SkyObject; x: number; y: number } | null>(null)

  function onMove(event: React.PointerEvent<HTMLDivElement>) {
    const rect = box.current?.getBoundingClientRect()
    if (!rect || rect.width === 0) return
    const px = event.clientX - rect.left
    const py = event.clientY - rect.top
    let best: SkyObject | null = null
    let bestDistance = HIT_RADIUS_PX
    for (const object of objects) {
      // Brighter objects win ties: a bright star next to a faint one is the one asked about.
      const distance = Math.hypot(object.x * rect.width - px, object.y * rect.height - py) + object.mag * 0.4
      if (distance < bestDistance) {
        best = object
        bestDistance = distance
      }
    }
    setHover(best ? { object: best, x: best.x * rect.width, y: best.y * rect.height } : null)
  }

  return (
    <div ref={box} className="relative" onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
      {children}
      {hover ? (
        <>
          <span
            className="pointer-events-none absolute h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-amber"
            style={{ left: hover.x, top: hover.y }}
          />
          <div
            role="tooltip"
            className="pointer-events-none absolute z-10 -translate-x-1/2 whitespace-nowrap rounded-md border border-border bg-panel px-2 py-1 text-xs text-ink shadow-md"
            style={{ left: hover.x, top: hover.y + 16 }}
          >
            {describe(hover.object)}
          </div>
        </>
      ) : null}
    </div>
  )
}

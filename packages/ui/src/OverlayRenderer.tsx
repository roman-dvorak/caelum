import type { FrameMetadata, OverlayElement } from '@caelum/api-client'
import { periodLabel } from './periods.js'
import { readFractionalBox, readNumber, readString } from './overlayPayload.js'

export interface OverlayRendererProps {
  metadata: FrameMetadata
  className?: string
}

/**
 * Draws `metadata.overlay_elements` as absolutely-positioned layers over an
 * image. Meant to be stacked inside a `position: relative` box that exactly
 * matches the rendered image (see `ImageViewer`, which does this for you).
 *
 * Every known element `type` gets a purpose-built visual; anything else
 * falls back to a generic label (or nothing, if it doesn't even carry
 * enough shape to place a marker) rather than throwing — overlay types are
 * an open set by design, since plugins can introduce new ones.
 */
export function OverlayRenderer({ metadata, className }: OverlayRendererProps) {
  return (
    <div className={['pointer-events-none absolute inset-0 overflow-hidden', className ?? ''].join(' ')}>
      {metadata.overlay_elements.map((element, index) => (
        <OverlayElementView key={`${element.source}:${element.type}:${index}`} element={element} />
      ))}
    </div>
  )
}

function OverlayElementView({ element }: { element: OverlayElement }) {
  switch (element.type) {
    case 'timestamp':
      return <TimestampLabel payload={element.payload} />
    case 'exposure_readout':
      return <ExposureReadoutLabel payload={element.payload} />
    case 'sky_state_badge':
      return <SkyStateBadgeLabel payload={element.payload} />
    case 'detection_box':
      return <DetectionBoxMarker payload={element.payload} label={readString(element.payload, 'label')} />
    default:
      return <UnknownOverlayMarker element={element} />
  }
}

function TimestampLabel({ payload }: { payload: Record<string, unknown> }) {
  const text = readString(payload, 'text')
  if (!text) return null
  return (
    <div className="absolute bottom-2 left-2 rounded bg-black/60 px-2 py-1 font-mono text-xs text-slate-100">
      {text}
    </div>
  )
}

function ExposureReadoutLabel({ payload }: { payload: Record<string, unknown> }) {
  const exposureUs = readNumber(payload, 'exposure_us')
  const gain = readNumber(payload, 'analogue_gain')
  if (exposureUs === undefined && gain === undefined) return null
  return (
    <div className="absolute bottom-2 right-2 rounded bg-black/60 px-2 py-1 font-mono text-xs text-slate-100">
      {exposureUs !== undefined ? <span>{formatExposure(exposureUs)}</span> : null}
      {exposureUs !== undefined && gain !== undefined ? <span className="mx-1 opacity-60">·</span> : null}
      {gain !== undefined ? <span>ISO×{gain.toFixed(1)}</span> : null}
    </div>
  )
}

function SkyStateBadgeLabel({ payload }: { payload: Record<string, unknown> }) {
  const period = readString(payload, 'period')
  const sunAlt = readNumber(payload, 'sun_altitude_deg')
  const moonIllum = readNumber(payload, 'moon_illumination')
  if (!period) return null
  return (
    <div className="absolute top-2 left-2 flex items-center gap-2 rounded-full bg-black/60 px-2.5 py-1 text-xs text-slate-100 ring-1 ring-white/10">
      <span className="font-medium">{periodLabel(period)}</span>
      {sunAlt !== undefined ? <span className="opacity-80">☉ {sunAlt.toFixed(1)}°</span> : null}
      {moonIllum !== undefined ? <span className="opacity-80">☾ {Math.round(moonIllum * 100)}%</span> : null}
    </div>
  )
}

function DetectionBoxMarker({
  payload,
  label,
}: {
  payload: Record<string, unknown>
  label: string | undefined
}) {
  const box = readFractionalBox(payload)
  if (!box) return null
  return (
    <div
      className="absolute border-2 border-amber-400 shadow-[0_0_0_1px_rgba(0,0,0,0.5)]"
      style={{
        left: `${box.x * 100}%`,
        top: `${box.y * 100}%`,
        width: `${box.w * 100}%`,
        height: `${box.h * 100}%`,
      }}
    >
      {label ? (
        <span className="absolute -top-5 left-0 whitespace-nowrap rounded bg-amber-400 px-1 text-[10px] font-semibold text-black">
          {label}
        </span>
      ) : null}
    </div>
  )
}

/** Best-effort visual for an overlay type this renderer doesn't know about:
 * a bounding box if the payload happens to look like one, otherwise just a
 * small unobtrusive tag naming the type — never a crash. */
function UnknownOverlayMarker({ element }: { element: OverlayElement }) {
  const box = readFractionalBox(element.payload)
  const label = readString(element.payload, 'label') ?? element.type
  if (box) {
    return (
      <div
        className="absolute border-2 border-dashed border-fuchsia-400/80"
        style={{
          left: `${box.x * 100}%`,
          top: `${box.y * 100}%`,
          width: `${box.w * 100}%`,
          height: `${box.h * 100}%`,
        }}
      >
        <span className="absolute -top-5 left-0 whitespace-nowrap rounded bg-fuchsia-400/80 px-1 text-[10px] font-semibold text-black">
          {label}
        </span>
      </div>
    )
  }
  return (
    <div className="absolute top-2 right-2 rounded bg-black/50 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-400 ring-1 ring-white/10">
      {element.type}
    </div>
  )
}

function formatExposure(exposureUs: number): string {
  if (exposureUs >= 1_000_000) return `${(exposureUs / 1_000_000).toFixed(2)}s`
  if (exposureUs >= 1_000) return `${(exposureUs / 1_000).toFixed(1)}ms`
  return `${exposureUs}µs`
}

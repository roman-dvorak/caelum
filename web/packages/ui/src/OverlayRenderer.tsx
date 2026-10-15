import type { FrameMetadata, OverlayElement } from '@caelum/api-client'
import { periodLabel } from './periods.js'
import { readFractionalBox, readNumber, readString } from './overlayPayload.js'

/** Resolves a `custom_image` element's `payload.asset` (a bare filename) to
 * a fetchable URL. Each app supplies its own — local-web resolves against
 * its own API, remote-web against a camera's static archive prefix — since
 * that's the one thing this shared component cannot know on its own.
 * Defaults to treating `asset` as already a full URL, so callers that don't
 * pass one (or elements with no `custom_image` in play) are unaffected. */
export type AssetUrlResolver = (asset: string) => string

const defaultResolveAssetUrl: AssetUrlResolver = (asset) => asset

export interface OverlayRendererProps {
  metadata: FrameMetadata
  className?: string
  resolveAssetUrl?: AssetUrlResolver
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
export function OverlayRenderer({ metadata, className, resolveAssetUrl }: OverlayRendererProps) {
  return (
    <div className={['pointer-events-none absolute inset-0 overflow-hidden', className ?? ''].join(' ')}>
      {metadata.overlay_elements.map((element, index) => (
        <OverlayElementView
          key={`${element.source}:${element.type}:${index}`}
          element={element}
          resolveAssetUrl={resolveAssetUrl ?? defaultResolveAssetUrl}
        />
      ))}
    </div>
  )
}

function OverlayElementView({
  element,
  resolveAssetUrl,
}: {
  element: OverlayElement
  resolveAssetUrl: AssetUrlResolver
}) {
  switch (element.type) {
    case 'timestamp':
      return <TimestampLabel payload={element.payload} />
    case 'exposure_readout':
      return <ExposureReadoutLabel payload={element.payload} />
    case 'sky_state_badge':
      return <SkyStateBadgeLabel payload={element.payload} />
    case 'detection_box':
      return <DetectionBoxMarker payload={element.payload} label={readString(element.payload, 'label')} />
    case 'mask':
      return <MaskBox payload={element.payload} />
    case 'custom_label':
      return <CustomLabel payload={element.payload} />
    case 'custom_image':
      return <CustomImage payload={element.payload} resolveAssetUrl={resolveAssetUrl} />
    case 'telescope_marker':
      return <TelescopeMarker payload={element.payload} />
    default:
      return <UnknownOverlayMarker element={element} />
  }
}

const chip = 'bg-void/70 px-2 py-1 font-mono text-[11px] text-ink ring-1 ring-line backdrop-blur-sm'

function TimestampLabel({ payload }: { payload: Record<string, unknown> }) {
  const text = readString(payload, 'text')
  if (!text) return null
  return <div className={['absolute bottom-2 left-2', chip].join(' ')}>{text}</div>
}

function ExposureReadoutLabel({ payload }: { payload: Record<string, unknown> }) {
  const exposureUs = readNumber(payload, 'exposure_us')
  const gain = readNumber(payload, 'analogue_gain')
  if (exposureUs === undefined && gain === undefined) return null
  return (
    <div className={['tabular-nums absolute right-2 bottom-2 text-amber-bright', chip].join(' ')}>
      {exposureUs !== undefined ? <span>{formatExposure(exposureUs)}</span> : null}
      {exposureUs !== undefined && gain !== undefined ? <span className="mx-1.5 text-ink-faint">/</span> : null}
      {gain !== undefined ? <span>{gain.toFixed(1)}×</span> : null}
    </div>
  )
}

function SkyStateBadgeLabel({ payload }: { payload: Record<string, unknown> }) {
  const period = readString(payload, 'period')
  const sunAlt = readNumber(payload, 'sun_altitude_deg')
  const moonIllum = readNumber(payload, 'moon_illumination')
  if (!period) return null
  return (
    <div className={['tabular-nums absolute top-2 left-2 flex items-center gap-2', chip].join(' ')}>
      <span className="font-sans font-semibold tracking-wide text-amber uppercase">{periodLabel(period)}</span>
      {sunAlt !== undefined ? <span className="text-ink-dim">☉{sunAlt.toFixed(1)}°</span> : null}
      {moonIllum !== undefined ? <span className="text-ink-dim">☾{Math.round(moonIllum * 100)}%</span> : null}
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
      className="absolute border-2 border-amber shadow-[0_0_0_1px_rgba(0,0,0,0.6),0_0_12px_rgba(232,161,58,0.5)]"
      style={{
        left: `${box.x * 100}%`,
        top: `${box.y * 100}%`,
        width: `${box.w * 100}%`,
        height: `${box.h * 100}%`,
      }}
    >
      {label ? (
        <span className="absolute -top-5 left-0 bg-amber px-1 text-[10px] font-semibold whitespace-nowrap text-void">
          {label}
        </span>
      ) : null}
    </div>
  )
}

function MaskBox({ payload }: { payload: Record<string, unknown> }) {
  const box = readFractionalBox(payload)
  if (!box) return null
  const color = readString(payload, 'color') ?? '#000000'
  const opacity = readNumber(payload, 'opacity') ?? 1
  return (
    <div
      className="absolute"
      style={{
        left: `${box.x * 100}%`,
        top: `${box.y * 100}%`,
        width: `${box.w * 100}%`,
        height: `${box.h * 100}%`,
        backgroundColor: color,
        opacity,
      }}
    />
  )
}

function CustomLabel({ payload }: { payload: Record<string, unknown> }) {
  const text = readString(payload, 'text')
  const x = readNumber(payload, 'x')
  const y = readNumber(payload, 'y')
  if (!text || x === undefined || y === undefined) return null
  const color = readString(payload, 'color') ?? '#e5e5e5'
  const fontSize = readNumber(payload, 'font_size_px')
  return (
    <div
      className="absolute -translate-x-1/2 -translate-y-1/2 font-mono whitespace-nowrap"
      style={{ left: `${x * 100}%`, top: `${y * 100}%`, color, fontSize: fontSize ? `${fontSize}px` : undefined }}
    >
      {text}
    </div>
  )
}

function CustomImage({
  payload,
  resolveAssetUrl,
}: {
  payload: Record<string, unknown>
  resolveAssetUrl: AssetUrlResolver
}) {
  const box = readFractionalBox(payload)
  const asset = readString(payload, 'asset')
  if (!box || !asset) return null
  return (
    <img
      src={resolveAssetUrl(asset)}
      alt=""
      className="absolute h-full w-full object-contain"
      style={{
        left: `${box.x * 100}%`,
        top: `${box.y * 100}%`,
        width: `${box.w * 100}%`,
        height: `${box.h * 100}%`,
      }}
    />
  )
}

function TelescopeMarker({ payload }: { payload: Record<string, unknown> }) {
  const x = readNumber(payload, 'x')
  const y = readNumber(payload, 'y')
  if (x === undefined || y === undefined) return null
  const label = readString(payload, 'label')
  return (
    <div
      className="absolute -translate-x-1/2 -translate-y-1/2"
      style={{ left: `${x * 100}%`, top: `${y * 100}%` }}
    >
      <div className="h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-amber bg-amber/30" />
      {label ? (
        <span className="absolute top-2 left-1/2 -translate-x-1/2 bg-void/70 px-1 text-[10px] whitespace-nowrap text-amber-bright">
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
        className="absolute border-2 border-dashed border-cyan/80"
        style={{
          left: `${box.x * 100}%`,
          top: `${box.y * 100}%`,
          width: `${box.w * 100}%`,
          height: `${box.h * 100}%`,
        }}
      >
        <span className="absolute -top-5 left-0 bg-cyan/80 px-1 text-[10px] font-semibold whitespace-nowrap text-void">
          {label}
        </span>
      </div>
    )
  }
  return (
    <div className={['absolute top-2 right-2 text-ink-faint uppercase', chip].join(' ')}>{element.type}</div>
  )
}

function formatExposure(exposureUs: number): string {
  if (exposureUs >= 1_000_000) return `${(exposureUs / 1_000_000).toFixed(2)}s`
  if (exposureUs >= 1_000) return `${(exposureUs / 1_000).toFixed(1)}ms`
  return `${exposureUs}µs`
}

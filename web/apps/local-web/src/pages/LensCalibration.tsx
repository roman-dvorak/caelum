import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Field, Message, PageHeader, Panel, Readout, StatusBadge, inputClass } from '@caelum/ui'
import type { LensCircleDetection, LensConfig, LensProjection, LensStarFit, SkyObject } from '@caelum/api-client'
import { useFrameStream } from '../hooks/useFrameStream.ts'
import { useSkyObjects } from '../hooks/useSkyObjects.ts'
import { altAzToFraction, compassPoint, fractionToAltAz } from '../lib/lensMath.ts'
import { localApiClient } from '../services/client.ts'

const PROJECTIONS: { value: LensProjection; label: string }[] = [
  { value: 'equidistant_fisheye', label: 'Equidistant (r ∝ θ) — most allsky lenses' },
  { value: 'equisolid_fisheye', label: 'Equisolid (r ∝ sin θ/2)' },
  { value: 'stereographic_fisheye', label: 'Stereographic (r ∝ tan θ/2)' },
  { value: 'orthographic_fisheye', label: 'Orthographic (r ∝ sin θ)' },
]

const FALLBACK_LENS: LensConfig = {
  projection: 'equidistant_fisheye',
  center_x: 0.5,
  center_y: 0.5,
  radius: 0.48,
  fov_deg: 180,
  azimuth_offset_deg: 0,
  mirror: false,
}

const STAR_RING_COLOR = '#e8f1ff'
const GRID_COLOR = '#50c8dc'
const HIT_RADIUS_PX = 14

function round(value: number, digits: number): number {
  const k = 10 ** digits
  return Math.round(value * k) / k
}

interface Hover {
  x: number
  y: number
  text: string
}

export function LensCalibration() {
  const { frame, status: streamStatus } = useFrameStream()
  const sky = useSkyObjects(5.0)

  const [saved, setSaved] = useState<LensConfig | null>(null)
  const [lens, setLens] = useState<LensConfig>(FALLBACK_LENS)
  const [maxMag, setMaxMag] = useState(3.5)
  const [showGrid, setShowGrid] = useState(true)
  const [showStars, setShowStars] = useState(true)
  const [pickCenter, setPickCenter] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<{ kind: 'info' | 'error' | 'success'; text: string } | null>(null)
  const [circle, setCircle] = useState<LensCircleDetection | null>(null)
  const [fit, setFit] = useState<LensStarFit | null>(null)
  const [hover, setHover] = useState<Hover | null>(null)
  const [overlayEnabled, setOverlayEnabled] = useState<boolean | null>(null)

  const stage = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [naturalAspect, setNaturalAspect] = useState<number | null>(null)
  const aspect = sky?.aspect ?? naturalAspect ?? 4 / 3

  useEffect(() => {
    let cancelled = false
    void Promise.all([localApiClient.getConfig(), localApiClient.getPlugins()])
      .then(([config, plugins]) => {
        if (cancelled) return
        setSaved(config.camera.lens)
        setLens(config.camera.lens)
        const entry = (plugins as unknown as { plugins?: { id: string; enabled: boolean }[] }).plugins?.find(
          (p) => p.id === 'sky_overlay',
        )
        setOverlayEnabled(entry ? entry.enabled : null)
      })
      .catch((err) => setMessage({ kind: 'error', text: err instanceof Error ? err.message : String(err) }))
    return () => {
      cancelled = true
    }
  }, [])

  const change = useCallback((patch: Partial<LensConfig>) => setLens((current) => ({ ...current, ...patch })), [])
  const dirty = useMemo(() => saved !== null && JSON.stringify(saved) !== JSON.stringify(lens), [saved, lens])

  // The candidate lens applied to the sky — recomputed on every change, in the browser.
  const projected = useMemo(() => {
    const out: (SkyObject & { px: number; py: number })[] = []
    for (const object of sky?.objects ?? []) {
      if (object.kind === 'star' && (!showStars || object.mag > maxMag)) continue
      const point = altAzToFraction(lens, aspect, object.alt_deg, object.az_deg)
      if (point && point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1) out.push({ ...object, px: point.x, py: point.y })
    }
    return out
  }, [sky, lens, aspect, maxMag, showStars])

  // ---- drawing ------------------------------------------------------------
  useEffect(() => {
    const el = canvas.current
    const box = stage.current
    if (!el || !box) return
    const ratio = window.devicePixelRatio || 1
    const w = box.clientWidth
    const h = box.clientHeight
    el.width = Math.round(w * ratio)
    el.height = Math.round(h * ratio)
    el.style.width = `${w}px`
    el.style.height = `${h}px`
    const ctx = el.getContext('2d')
    if (!ctx) return
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
    ctx.clearRect(0, 0, w, h)

    // The image circle and the optical centre.
    const cx = lens.center_x * w
    const cy = lens.center_y * h
    const r = lens.radius * Math.min(w, h)
    ctx.lineWidth = 1.5
    ctx.strokeStyle = '#f6be64'
    ctx.beginPath()
    ctx.arc(cx, cy, r, 0, Math.PI * 2)
    ctx.stroke()
    ctx.beginPath()
    ctx.moveTo(cx - 10, cy)
    ctx.lineTo(cx + 10, cy)
    ctx.moveTo(cx, cy - 10)
    ctx.lineTo(cx, cy + 10)
    ctx.stroke()

    const toPx = (alt: number, az: number): [number, number] | null => {
      const p = altAzToFraction(lens, aspect, alt, az)
      return p ? [p.x * w, p.y * h] : null
    }

    if (showGrid) {
      ctx.strokeStyle = GRID_COLOR
      ctx.globalAlpha = 0.6
      ctx.lineWidth = 1
      const horizon = Math.max(0, 90 - lens.fov_deg / 2)
      const line = (points: ([number, number] | null)[]) => {
        ctx.beginPath()
        let pen = false
        for (const p of points) {
          if (!p) {
            pen = false
            continue
          }
          if (pen) ctx.lineTo(p[0], p[1])
          else ctx.moveTo(p[0], p[1])
          pen = true
        }
        ctx.stroke()
      }
      for (const alt of [0, 30, 60]) {
        if (alt < horizon) continue
        line(Array.from({ length: 73 }, (_, i) => toPx(alt, i * 5)))
      }
      for (const az of [0, 90, 180, 270]) {
        line(Array.from({ length: 19 }, (_, i) => toPx(Math.min(90, horizon + i * 5), az)))
      }
      ctx.globalAlpha = 1
      ctx.font = 'bold 15px ui-monospace, monospace'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      for (const [letter, az] of [['N', 0], ['E', 90], ['S', 180], ['W', 270]] as const) {
        const p = toPx(horizon + 7, az)
        if (!p) continue
        ctx.fillStyle = 'rgba(8,10,14,0.7)'
        ctx.fillRect(p[0] - 10, p[1] - 10, 20, 20)
        ctx.fillStyle = letter === 'N' ? '#ff6e64' : '#e5e5e5'
        ctx.fillText(letter, p[0], p[1])
      }
    }

    // Matched stars from the last fit: where the camera saw them, as small crosses.
    if (fit) {
      ctx.strokeStyle = '#7CFC9A'
      ctx.lineWidth = 1
      for (const m of fit.matches) {
        const x = (m.x / fit.image_width) * w
        const y = (m.y / fit.image_height) * h
        ctx.strokeRect(x - 3, y - 3, 6, 6)
      }
    }

    for (const o of projected) {
      const x = o.px * w
      const y = o.py * h
      if (o.kind === 'star') {
        const size = Math.max(3, 3 + (4.5 - o.mag) * 1.6)
        ctx.strokeStyle = STAR_RING_COLOR
        ctx.globalAlpha = 0.85
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.arc(x, y, size, 0, Math.PI * 2)
        ctx.stroke()
        ctx.globalAlpha = 1
        if (o.mag <= 1.6) {
          ctx.fillStyle = 'rgba(232,241,255,0.95)'
          ctx.font = '11px ui-monospace, monospace'
          ctx.textAlign = 'left'
          ctx.textBaseline = 'middle'
          ctx.fillText(o.name, x + size + 3, y)
        }
      } else {
        ctx.strokeStyle = o.kind === 'sun' ? '#ffd65a' : o.kind === 'moon' ? '#dce0e8' : '#e8a13a'
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.arc(x, y, o.kind === 'planet' ? 5 : 8, 0, Math.PI * 2)
        ctx.stroke()
        ctx.fillStyle = ctx.strokeStyle
        ctx.font = '11px ui-monospace, monospace'
        ctx.textAlign = 'left'
        ctx.textBaseline = 'middle'
        ctx.fillText(o.name, x + 12, y)
      }
    }
  }, [lens, projected, showGrid, aspect, fit, frame?.imageBlobUrl])

  // Redraw when the box is resized (window, sidebar).
  const [, setResizeTick] = useState(0)
  useEffect(() => {
    const box = stage.current
    if (!box) return
    const observer = new ResizeObserver(() => setResizeTick((n) => n + 1))
    observer.observe(box)
    return () => observer.disconnect()
  }, [])

  // ---- pointer ------------------------------------------------------------
  function fractions(event: React.PointerEvent<HTMLDivElement>): { x: number; y: number; w: number; h: number } | null {
    const rect = stage.current?.getBoundingClientRect()
    if (!rect || rect.width === 0) return null
    return { x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height, w: rect.width, h: rect.height }
  }

  function onPointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const f = fractions(event)
    if (!f) return
    let best: (typeof projected)[number] | null = null
    let bestDistance = HIT_RADIUS_PX
    for (const o of projected) {
      const d = Math.hypot(o.px * f.w - f.x * f.w, o.py * f.h - f.y * f.h) + o.mag * 0.4
      if (d < bestDistance) {
        best = o
        bestDistance = d
      }
    }
    if (best) {
      const where = `alt ${best.alt_deg.toFixed(1)}° · az ${best.az_deg.toFixed(0)}° ${compassPoint(best.az_deg)}`
      setHover({
        x: best.px * f.w,
        y: best.py * f.h,
        text: best.kind === 'star' ? `${best.name} · mag ${best.mag.toFixed(1)} · ${where}` : `${best.name} · ${where}`,
      })
      return
    }
    const altaz = fractionToAltAz(lens, aspect, f.x, f.y)
    setHover(
      altaz
        ? { x: f.x * f.w, y: f.y * f.h, text: `alt ${altaz.alt.toFixed(1)}° · az ${altaz.az.toFixed(1)}° ${compassPoint(altaz.az)}` }
        : null,
    )
  }

  function onPointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (!pickCenter) return
    const f = fractions(event)
    if (!f) return
    change({ center_x: round(f.x, 4), center_y: round(f.y, 4) })
    setPickCenter(false)
  }

  // ---- actions ------------------------------------------------------------
  async function run(name: string, task: () => Promise<void>) {
    setBusy(name)
    setMessage(null)
    try {
      await task()
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy(null)
    }
  }

  const detectCircle = () =>
    run('circle', async () => {
      const found = await localApiClient.detectLensCircle()
      setCircle(found)
      change({ center_x: found.center_x, center_y: found.center_y, radius: found.radius })
      setMessage({
        kind: found.confidence >= 0.8 ? 'success' : 'info',
        text:
          `Image circle: centre ${(found.center_x * 100).toFixed(1)} % / ${(found.center_y * 100).toFixed(1)} %, ` +
          `radius ${found.radius_px.toFixed(0)} px (${(found.confidence * 100).toFixed(0)} % of the edge fits)` +
          (found.cropped ? ' — the disc is cut off by the frame; only its visible edge was used.' : '.') +
          (found.confidence < 0.8 ? ' The edge is not clean — check the circle by eye.' : ''),
      })
    })

  const fitStars = (fitFov: boolean) =>
    run('stars', async () => {
      const result = await localApiClient.fitLensFromStars({ fit_fov: fitFov })
      setFit(result)
      setLens(result.lens)
      setMessage({
        kind: result.confidence >= 0.5 ? 'success' : 'info',
        text: `Fitted to ${result.matched} of ${result.candidates} catalog stars, RMS ${result.rms_px.toFixed(2)} px.`,
      })
    })

  const save = () =>
    run('save', async () => {
      const updated = await localApiClient.updateConfig({ camera: { lens } })
      setSaved(updated.camera.lens)
      setLens(updated.camera.lens)
      setMessage({ kind: 'success', text: 'Saved as camera.lens.' })
    })

  const enableOverlay = () =>
    run('overlay', async () => {
      await localApiClient.updatePlugin('sky_overlay', { enabled: true })
      setOverlayEnabled(true)
      setMessage({ kind: 'success', text: 'Sky overlay plugin enabled — it appears on the next frame.' })
    })

  const number = (key: keyof LensConfig, step: number, min: number, max: number, digits = 4) => (
    <input
      type="number"
      step={step}
      min={min}
      max={max}
      value={Number(lens[key])}
      onChange={(e) => {
        const value = Number(e.target.value)
        if (Number.isFinite(value)) change({ [key]: round(value, digits) } as Partial<LensConfig>)
      }}
      className={`${inputClass} w-32`}
    />
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Lens"
        actions={dirty ? <StatusBadge tone="live">Unsaved changes</StatusBadge> : <StatusBadge>Saved</StatusBadge>}
      />

      <p className="text-sm text-ink-muted">
        Tell caelum where the sky is in the image: the orange circle is the lens’ image circle, the rings are 0°, 30° and 60° altitude and the circled
        stars are where the catalog says they are right now. Make them sit on the real stars. Hover over the image for names and sky coordinates.
      </p>

      {message ? <Message kind={message.kind}>{message.text}</Message> : null}

      <Panel
        title="Frame"
        actions={
          <div className="flex items-center gap-4 text-label-md text-ink-muted">
            <label className="flex items-center gap-2 select-none">
              <input type="checkbox" checked={showGrid} onChange={(e) => setShowGrid(e.target.checked)} className="accent-amber" />
              Grid &amp; compass
            </label>
            <label className="flex items-center gap-2 select-none">
              <input type="checkbox" checked={showStars} onChange={(e) => setShowStars(e.target.checked)} className="accent-amber" />
              Stars
            </label>
          </div>
        }
        bodyClassName="p-0"
      >
        {frame ? (
          <div
            ref={stage}
            className={['relative leading-none', pickCenter ? 'cursor-crosshair' : ''].join(' ')}
            onPointerMove={onPointerMove}
            onPointerLeave={() => setHover(null)}
            onPointerDown={onPointerDown}
          >
            <img
              src={frame.imageBlobUrl}
              alt="Latest frame"
              className="block h-auto w-full"
              onLoad={(e) => setNaturalAspect(e.currentTarget.naturalWidth / e.currentTarget.naturalHeight)}
            />
            <canvas ref={canvas} className="pointer-events-none absolute inset-0" />
            {hover ? (
              <div
                role="tooltip"
                className="pointer-events-none absolute z-10 -translate-x-1/2 whitespace-nowrap rounded-md border border-border bg-panel px-2 py-1 text-xs text-ink shadow-md"
                style={{ left: hover.x, top: hover.y + 14 }}
              >
                {hover.text}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="flex aspect-video items-center justify-center text-sm text-ink-muted">
            {streamStatus === 'connecting' ? 'Connecting to live stream…' : 'Waiting for first frame…'}
          </div>
        )}
      </Panel>

      <Panel title="Find it automatically">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-3">
            <Button variant="primary" onClick={() => void detectCircle()} disabled={busy !== null || !frame}>
              {busy === 'circle' ? 'Detecting…' : 'Detect image circle'}
            </Button>
            <Button variant="primary" onClick={() => void fitStars(true)} disabled={busy !== null || !frame}>
              {busy === 'stars' ? 'Fitting… (up to a minute)' : 'Fit from stars'}
            </Button>
            <Button onClick={() => void fitStars(false)} disabled={busy !== null || !frame}>
              Fit from stars, keep field of view
            </Button>
          </div>
          <p className="text-sm text-ink-muted">
            <strong className="font-medium text-ink">Image circle</strong> works on any frame (day or night) where the lens disc is brighter than the
            black around it. <strong className="font-medium text-ink">Fit from stars</strong> needs a clear, dark night frame — no Moon, no clouds: it
            finds the stars in the image, works out which way north is and whether the lens mirrors the sky, then refines the centre, the field of view
            and which projection fits best.
          </p>
          {circle ? (
            <p className="text-sm text-ink-muted">
              Last circle: {circle.radius_px.toFixed(0)} px radius in a {circle.image_width}×{circle.image_height} frame, confidence{' '}
              {(circle.confidence * 100).toFixed(0)} %.
            </p>
          ) : null}
          {fit ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Readout label="Stars matched" value={`${fit.matched} / ${fit.candidates}`} />
              <Readout label="Residual (RMS)" value={`${fit.rms_px.toFixed(2)} px`} />
              <Readout label="Confidence" value={`${Math.round(fit.confidence * 100)} %`} />
              <Readout
                label="Projections (RMS px)"
                value={Object.entries(fit.by_projection)
                  .map(([name, rms]) => `${name.replace('_fisheye', '')} ${rms.toFixed(2)}`)
                  .join(' · ')}
              />
            </div>
          ) : null}
        </div>
      </Panel>

      <Panel title="Values">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-end gap-4">
            <Field label="Centre X (0–1)" hint="Optical centre / zenith, fraction of the width">
              {number('center_x', 0.001, 0, 1)}
            </Field>
            <Field label="Centre Y (0–1)" hint="fraction of the height">
              {number('center_y', 0.001, 0, 1)}
            </Field>
            <Field label="Radius" hint="Image circle edge, fraction of the shorter side">
              {number('radius', 0.001, 0.05, 1)}
            </Field>
            <Field label="Field of view (°)" hint="180 = the edge is the horizon">
              {number('fov_deg', 0.5, 90, 360, 2)}
            </Field>
            <Field label="North offset (°)" hint="Rotation of the camera against true north">
              {number('azimuth_offset_deg', 0.5, -360, 360, 2)}
            </Field>
          </div>
          <div className="flex flex-wrap items-end gap-4">
            <Field label="Projection">
              <select
                value={lens.projection}
                onChange={(e) => change({ projection: e.target.value as LensProjection })}
                className={`${inputClass} min-w-72`}
              >
                {PROJECTIONS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </Field>
            <label className="flex items-center gap-2 pb-2 text-sm text-ink select-none">
              <input type="checkbox" checked={lens.mirror} onChange={(e) => change({ mirror: e.target.checked })} className="accent-amber" />
              <span>
                Mirrored — east and west swapped.
                <span className="block text-xs text-ink-muted">A camera looking up with north at the top sees east on the left; that needs this ticked. “Fit from stars” decides it for you.</span>
              </span>
            </label>
            <Field label={`Faintest star shown: mag ${maxMag.toFixed(1)}`}>
              <input type="range" min={0} max={5} step={0.5} value={maxMag} onChange={(e) => setMaxMag(Number(e.target.value))} className="accent-amber" />
            </Field>
            <Button variant={pickCenter ? 'primary' : 'secondary'} onClick={() => setPickCenter((v) => !v)} disabled={!frame}>
              {pickCenter ? 'Click the centre on the image…' : 'Pick centre on image'}
            </Button>
          </div>
          <div className="flex flex-wrap gap-3 border-t border-border-subtle pt-4">
            <Button variant="primary" onClick={() => void save()} disabled={busy !== null || !dirty}>
              {busy === 'save' ? 'Saving…' : 'Save lens'}
            </Button>
            <Button variant="ghost" onClick={() => saved && setLens(saved)} disabled={!dirty}>
              Reset to saved
            </Button>
          </div>
        </div>
      </Panel>

      <Panel title="Sky overlay">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <p className="max-w-2xl text-sm text-ink-muted">
            With the lens saved, the <code>sky_overlay</code> plugin draws this sky — stars, planets, Sun, Moon, compass and altitude rings — into every
            frame’s overlay, and it follows the clock all night. Its options (faintest star, labels, colours) are on the Plugins page.
          </p>
          {overlayEnabled === null ? null : overlayEnabled ? (
            <StatusBadge tone="live">Enabled</StatusBadge>
          ) : (
            <Button variant="primary" onClick={() => void enableOverlay()} disabled={busy !== null || dirty}>
              Enable sky overlay
            </Button>
          )}
        </div>
      </Panel>
    </div>
  )
}

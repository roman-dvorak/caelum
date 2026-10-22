import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { Button, Field, Message, PageHeader, Panel } from '@caelum/ui'
import type { LiveWhiteBalanceFrame } from '@caelum/api-client'
import { localApiClient } from '../services/client.ts'

interface FractionalRect {
  x: number
  y: number
  w: number
  h: number
}

/** Mean camera RGB (0..1, not white-balanced) of the ROI's unclipped pixels. */
interface RoiStats {
  mean: [number, number, number]
  clipped: number
}

const DEFAULT_ROI: FractionalRect = { x: 0.4, y: 0.4, w: 0.2, h: 0.2 }
const GAIN_MIN = 0.1
const GAIN_MAX = 8
/** A pixel this close to the white level in any channel has lost its colour. */
const CLIP = 0.98 * 65535

const SRGB_LUT = (() => {
  const lut = new Uint8ClampedArray(4096)
  for (let i = 0; i < lut.length; i++) {
    const v = i / (lut.length - 1)
    lut[i] = Math.round(255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * Math.pow(v, 1 / 2.4) - 0.055))
  }
  return lut
})()

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function clampGain(value: number): number {
  return clamp(Math.round(value * 1000) / 1000, GAIN_MIN, GAIN_MAX)
}

/** Linear scale that puts the frame's median green at mid-gray — night
 * frames sit in the bottom percent of the range and would render black. */
function autoScale(pixels: Uint16Array): number {
  const samples: number[] = []
  const step = Math.max(1, Math.floor(pixels.length / 3 / 20000)) * 3
  for (let i = 1; i < pixels.length; i += step) samples.push(pixels[i])
  samples.sort((a, b) => a - b)
  const median = samples[samples.length >> 1] / 65535
  return clamp(0.18 / Math.max(median, 1e-5), 1, 2000)
}

function roiStats(frame: LiveWhiteBalanceFrame, roi: FractionalRect): RoiStats | null {
  const { width, height } = frame.info
  const p = frame.pixels
  const x0 = Math.floor(roi.x * width)
  const y0 = Math.floor(roi.y * height)
  const x1 = Math.min(width, Math.max(x0 + 1, Math.round((roi.x + roi.w) * width)))
  const y1 = Math.min(height, Math.max(y0 + 1, Math.round((roi.y + roi.h) * height)))
  let r = 0
  let g = 0
  let b = 0
  let n = 0
  let clipped = 0
  for (let y = y0; y < y1; y++) {
    for (let i = (y * width + x0) * 3, end = (y * width + x1) * 3; i < end; i += 3) {
      if (p[i] >= CLIP || p[i + 1] >= CLIP || p[i + 2] >= CLIP) {
        clipped++
        continue
      }
      r += p[i]
      g += p[i + 1]
      b += p[i + 2]
      n++
    }
  }
  const total = n + clipped
  if (total === 0) return null
  return { mean: n ? [r / n / 65535, g / n / 65535, b / n / 65535] : [0, 0, 0], clipped: clipped / total }
}

function render(
  canvas: HTMLCanvasElement,
  frame: LiveWhiteBalanceFrame,
  redGain: number,
  blueGain: number,
  scale: number,
) {
  const { width, height, render_matrix: m } = frame.info
  if (canvas.width !== width) canvas.width = width
  if (canvas.height !== height) canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const image = ctx.createImageData(width, height)
  const out = image.data
  const p = frame.pixels
  // gains, matrix, brightness and the LUT's index range folded into one 3x3
  const k = (scale * (SRGB_LUT.length - 1)) / 65535
  const gains = [redGain, 1, blueGain]
  const c = m.flatMap((row) => row.map((v, j) => v * gains[j] * k))
  const top = SRGB_LUT.length - 1
  for (let i = 0, o = 0; i < p.length; i += 3, o += 4) {
    const r = p[i]
    const g = p[i + 1]
    const b = p[i + 2]
    if (r >= CLIP || g >= CLIP || b >= CLIP) {
      out[o] = out[o + 1] = out[o + 2] = 255
    } else {
      out[o] = SRGB_LUT[clamp((c[0] * r + c[1] * g + c[2] * b) | 0, 0, top)]
      out[o + 1] = SRGB_LUT[clamp((c[3] * r + c[4] * g + c[5] * b) | 0, 0, top)]
      out[o + 2] = SRGB_LUT[clamp((c[6] * r + c[7] * g + c[8] * b) | 0, 0, top)]
    }
    out[o + 3] = 255
  }
  ctx.putImageData(image, 0, 0)
}

/** The ROI's mean as a display colour, brightness normalized — gray when neutral. */
function swatch(stats: RoiStats, m: number[][], redGain: number, blueGain: number): string {
  const balanced = [stats.mean[0] * redGain, stats.mean[1], stats.mean[2] * blueGain]
  const rgb = m.map((row) => Math.max(0, row[0] * balanced[0] + row[1] * balanced[1] + row[2] * balanced[2]))
  const peak = Math.max(...rgb, 1e-9)
  const [r, g, b] = rgb.map((v) => SRGB_LUT[Math.round((0.6 * v) / peak * (SRGB_LUT.length - 1))])
  return `rgb(${r}, ${g}, ${b})`
}

function signedPercent(value: number): string {
  const percent = value * 100
  return `${percent >= 0 ? '+' : '−'}${Math.abs(percent).toFixed(1)} %`
}

interface Progress {
  loaded: number
  total: number
}

/** `null` progress: the camera is still preparing the frame, no bytes yet. */
function loadingLabel(progress: Progress | null): string {
  if (!progress) return 'Preparing frame…'
  const mb = (bytes: number) => (bytes / 1e6).toFixed(1)
  return `Downloading ${Math.floor((100 * progress.loaded) / progress.total)} % · ${mb(progress.loaded)} / ${mb(progress.total)} MB`
}

function LoadingIndicator({ progress }: { progress: Progress | null }) {
  return (
    <div className="flex w-56 flex-col gap-1.5 text-xs text-ink-muted">
      <span>{loadingLabel(progress)}</span>
      <div className="h-1 overflow-hidden bg-border">
        {progress ? (
          <div className="h-full bg-amber transition-[width]" style={{ width: `${(100 * progress.loaded) / progress.total}%` }} />
        ) : (
          <div className="h-full w-1/3 animate-pulse bg-amber" />
        )}
      </div>
    </div>
  )
}

function verdict(deviation: number): { label: string; className: string } {
  if (deviation < 0.02) return { label: 'Neutral', className: 'text-success' }
  if (deviation < 0.05) return { label: 'Slight cast', className: 'text-success' }
  if (deviation < 0.15) return { label: 'Visible cast', className: 'text-amber-ink' }
  return { label: 'Strong cast', className: 'text-error' }
}

/**
 * White balance against the newest frame's raw data, straight from the
 * camera's RAM: the gains are applied here in the browser, so dragging is
 * instant and changes nothing until "Save to configuration".
 */
export function WhiteBalance() {
  const [frame, setFrame] = useState<LiveWhiteBalanceFrame | null>(null)
  const [loading, setLoading] = useState(true)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [redGain, setRedGain] = useState(1)
  const [blueGain, setBlueGain] = useState(1)
  const [config, setConfig] = useState<{ red: number; blue: number } | null>(null)
  const [ev, setEv] = useState(0)
  const [roi, setRoi] = useState<FractionalRect>(DEFAULT_ROI)
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const apply = useCallback((next: LiveWhiteBalanceFrame) => {
    setFrame(next)
    setRedGain(clampGain(next.info.red_gain))
    setBlueGain(clampGain(next.info.blue_gain))
    setConfig({ red: next.info.camera_red_gain, blue: next.info.camera_blue_gain })
    setLoading(false)
  }, [])

  const onProgress = useCallback((loaded: number, total: number) => setProgress({ loaded, total }), [])

  const fail = useCallback((err: unknown) => {
    setError(err instanceof Error ? err.message : String(err))
    setLoading(false)
  }, [])

  function load() {
    setLoading(true)
    setError(null)
    setSaved(null)
    setProgress(null)
    localApiClient.getLiveWhiteBalanceFrame(1024, onProgress).then(apply, fail)
  }

  useEffect(() => {
    let cancelled = false
    localApiClient
      .getLiveWhiteBalanceFrame(1024, (loaded, total) => !cancelled && onProgress(loaded, total))
      .then(
        (next) => !cancelled && apply(next),
        (err: unknown) => !cancelled && fail(err),
      )
    return () => {
      cancelled = true
    }
  }, [apply, fail, onProgress])

  const baseScale = useMemo(() => (frame ? autoScale(frame.pixels) : 1), [frame])
  const stats = useMemo(() => (frame ? roiStats(frame, roi) : null), [frame, roi])

  useEffect(() => {
    if (!frame || !canvasRef.current) return
    const canvas = canvasRef.current
    const id = requestAnimationFrame(() => render(canvas, frame, redGain, blueGain, baseScale * 2 ** ev))
    return () => cancelAnimationFrame(id)
  }, [frame, redGain, blueGain, baseScale, ev])

  async function save() {
    setSaving(true)
    setError(null)
    setSaved(null)
    try {
      const result = await localApiClient.setWhiteBalance({ red_gain: redGain, blue_gain: blueGain })
      setConfig({ red: result.red_gain, blue: result.blue_gain })
      setSaved('Saved to the configuration — new frames use these gains from the next capture.')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  function startRoiDrag(startEvent: ReactPointerEvent, mode: 'move' | 'resize') {
    startEvent.stopPropagation()
    startEvent.preventDefault()
    const container = containerRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    const start = { ...roi }
    const startClientX = startEvent.clientX
    const startClientY = startEvent.clientY

    function onMove(moveEvent: PointerEvent) {
      const dx = (moveEvent.clientX - startClientX) / rect.width
      const dy = (moveEvent.clientY - startClientY) / rect.height
      if (mode === 'move') {
        setRoi({ ...start, x: clamp(start.x + dx, 0, 1 - start.w), y: clamp(start.y + dy, 0, 1 - start.h) })
      } else {
        setRoi({ ...start, w: clamp(start.w + dx, 0.02, 1 - start.x), h: clamp(start.h + dy, 0.02, 1 - start.y) })
      }
    }
    function onUp() {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const usable = stats !== null && stats.mean[0] > 0 && stats.mean[1] > 0 && stats.mean[2] > 0
  // Balanced R/G and B/G in the ROI: 1 is neutral.
  const redRatio = usable ? (stats.mean[0] * redGain) / stats.mean[1] : 1
  const blueRatio = usable ? (stats.mean[2] * blueGain) / stats.mean[1] : 1
  const deviation = Math.max(Math.abs(redRatio - 1), Math.abs(blueRatio - 1))
  const neutralRed = usable ? clampGain(stats.mean[1] / stats.mean[0]) : null
  const neutralBlue = usable ? clampGain(stats.mean[1] / stats.mean[2]) : null
  const dirty = config !== null && (Math.abs(config.red - redGain) > 1e-3 || Math.abs(config.blue - blueGain) > 1e-3)
  const status = verdict(deviation)

  return (
    <>
      <PageHeader
        title="White balance"
        description="Loads the newest frame's raw data from the camera's memory and previews gains on it instantly. Nothing changes until you save to the configuration."
      />

      {error ? <Message kind="error">{error}</Message> : null}
      {saved ? <Message kind="success">{saved}</Message> : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <div className="flex flex-col gap-2">
          <div ref={containerRef} className="relative overflow-hidden border border-border bg-surface-0 rounded-md">
            {frame ? (
              <canvas ref={canvasRef} className="block h-auto w-full" />
            ) : (
              <div className="flex aspect-video items-center justify-center text-sm text-ink-muted">
                {loading ? <LoadingIndicator progress={progress} /> : 'No frame loaded'}
              </div>
            )}
            {frame ? (
              <div
                onPointerDown={(e) => startRoiDrag(e, 'move')}
                className="absolute cursor-move border-2 border-amber rounded-md"
                style={{
                  left: `${roi.x * 100}%`,
                  top: `${roi.y * 100}%`,
                  width: `${roi.w * 100}%`,
                  height: `${roi.h * 100}%`,
                }}
              >
                <div
                  onPointerDown={(e) => startRoiDrag(e, 'resize')}
                  className="absolute -right-1.5 -bottom-1.5 h-3 w-3 cursor-nwse-resize border border-surface-0 bg-amber rounded-md"
                />
              </div>
            ) : null}
            {frame && loading ? (
              <div className="absolute inset-0 flex items-center justify-center bg-surface-0/70">
                <LoadingIndicator progress={progress} />
              </div>
            ) : null}
          </div>
          {frame ? (
            <p className="text-xs text-ink-muted">
              Frame {new Date(frame.info.captured_at).toLocaleString()} · {(frame.info.exposure_us / 1e6).toFixed(3)} s ·
              gain {frame.info.analogue_gain.toFixed(2)} · taken with R {frame.info.red_gain.toFixed(3)} / B{' '}
              {frame.info.blue_gain.toFixed(3)}. Colours match the camera; tones are a plain stretch, not the JPEG's curve.
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-3">
          <Panel title="Frame">
            <div className="flex flex-col gap-3">
              <Button onClick={load} disabled={loading} className={`relative overflow-hidden ${loading ? 'disabled:opacity-100' : ''}`}>
                {loading ? (
                  <span
                    className="absolute inset-y-0 left-0 bg-amber/25 transition-[width]"
                    style={{ width: progress ? `${(100 * progress.loaded) / progress.total}%` : '0%' }}
                  />
                ) : null}
                <span className="relative">{loading ? loadingLabel(progress) : 'Load latest frame'}</span>
              </Button>
              <Field label={`Preview brightness (${ev >= 0 ? '+' : ''}${ev.toFixed(1)} EV)`}>
                <input type="range" min={-4} max={4} step={0.1} value={ev} onChange={(e) => setEv(Number(e.target.value))} />
              </Field>
            </div>
          </Panel>

          <Panel title="Gains">
            <div className="flex flex-col gap-3">
              <Field label={`Red gain (${redGain.toFixed(3)})`}>
                <input
                  type="range"
                  min={GAIN_MIN}
                  max={GAIN_MAX}
                  step={0.005}
                  value={redGain}
                  disabled={!frame}
                  onChange={(e) => setRedGain(Number(e.target.value))}
                />
              </Field>
              <Field label={`Blue gain (${blueGain.toFixed(3)})`}>
                <input
                  type="range"
                  min={GAIN_MIN}
                  max={GAIN_MAX}
                  step={0.005}
                  value={blueGain}
                  disabled={!frame}
                  onChange={(e) => setBlueGain(Number(e.target.value))}
                />
              </Field>
              <div className="flex gap-2">
                <Button
                  className="flex-1"
                  disabled={!frame}
                  onClick={() => {
                    if (!frame) return
                    setRedGain(clampGain(frame.info.red_gain))
                    setBlueGain(clampGain(frame.info.blue_gain))
                  }}
                >
                  Frame's gains
                </Button>
                <Button
                  className="flex-1"
                  disabled={!config}
                  onClick={() => {
                    if (!config) return
                    setRedGain(clampGain(config.red))
                    setBlueGain(clampGain(config.blue))
                  }}
                >
                  Saved gains
                </Button>
              </div>
              <p className="text-xs text-ink-muted">
                Saved: {config ? `R ${config.red.toFixed(3)} / B ${config.blue.toFixed(3)}` : '—'}
                {dirty ? <span className="text-amber-ink"> · differs from the preview</span> : null}
              </p>
              <Button variant="primary" onClick={() => void save()} disabled={!frame || !dirty || saving}>
                {saving ? 'Saving…' : 'Save to configuration'}
              </Button>
            </div>
          </Panel>

          <Panel title="ROI neutrality">
            <div className="flex flex-col gap-2 text-sm">
              <p className="text-xs text-ink-muted">
                Drag the amber box over something that should be gray or white — a card, a cloud, the dome. How far
                its colour is from neutral with the current gains:
              </p>
              {frame && stats && usable ? (
                <>
                  <div className="flex items-center gap-3">
                    <div
                      className="h-10 w-10 shrink-0 border border-border rounded-md"
                      style={{ background: swatch(stats, frame.info.render_matrix, redGain, blueGain) }}
                    />
                    <div>
                      <div className={`font-semibold ${status.className}`}>{status.label}</div>
                      <div className="font-mono text-xs text-ink-muted">
                        R/G {signedPercent(redRatio - 1)} · B/G {signedPercent(blueRatio - 1)}
                      </div>
                    </div>
                  </div>
                  <p className="font-mono text-xs text-ink-muted">
                    Neutral at R {neutralRed?.toFixed(3)} / B {neutralBlue?.toFixed(3)}
                  </p>
                  {stats.mean[1] < 0.002 ? (
                    <p className="text-xs text-amber-ink">
                      The ROI is very dark ({(stats.mean[1] * 100).toFixed(2)} % of full scale) — noise dominates
                      the measurement.
                    </p>
                  ) : null}
                  {stats.clipped > 0.05 ? (
                    <p className="text-xs text-amber-ink">
                      {(stats.clipped * 100).toFixed(0)} % of the ROI is clipped (left out).
                    </p>
                  ) : null}
                  <Button
                    onClick={() => {
                      if (neutralRed === null || neutralBlue === null) return
                      setRedGain(neutralRed)
                      setBlueGain(neutralBlue)
                    }}
                  >
                    Make ROI neutral
                  </Button>
                </>
              ) : (
                <p className="text-xs text-ink-muted">
                  {frame ? 'No usable signal in the ROI (black or clipped).' : 'Load a frame first.'}
                </p>
              )}
            </div>
          </Panel>
        </div>
      </div>
    </>
  )
}

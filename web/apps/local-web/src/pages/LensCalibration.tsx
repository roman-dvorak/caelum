import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button,
  Field,
  Message,
  PageHeader,
  Panel,
  Readout,
  SkyCanvas,
  SkySettingsMenu,
  StatusBadge,
  inputClass,
  useSkySettings,
} from '@caelum/ui'
import type { LensCircleDetection, LensConfig, LensProjection, LensStarFit } from '@caelum/api-client'
import { useFrameStream } from '../hooks/useFrameStream.ts'
import { useSkySetup } from '../hooks/useSkySetup.ts'
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


function round(value: number, digits: number): number {
  const k = 10 ** digits
  return Math.round(value * k) / k
}

export function LensCalibration() {
  const { frame, status: streamStatus } = useFrameStream()

  const [saved, setSaved] = useState<LensConfig | null>(null)
  const [lens, setLens] = useState<LensConfig>(FALLBACK_LENS)
  const [pickCenter, setPickCenter] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<{ kind: 'info' | 'error' | 'success'; text: string } | null>(null)
  const [circle, setCircle] = useState<LensCircleDetection | null>(null)
  const [fit, setFit] = useState<LensStarFit | null>(null)
  const skySetup = useSkySetup()
  const [skyView, updateSkyView] = useSkySettings()
  const [overlayEnabled, setOverlayEnabled] = useState<boolean | null>(null)


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

  // The matched stars of the last fit, drawn by the sky canvas after the sky: where the camera saw them.
  const drawMatches = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number) => {
      if (!fit) return
      ctx.strokeStyle = '#7CFC9A'
      ctx.lineWidth = 1
      for (const m of fit.matches) {
        ctx.strokeRect((m.x / fit.image_width) * w - 3, (m.y / fit.image_height) * h - 3, 6, 6)
      }
    },
    [fit],
  )

  function onPick(x: number, y: number) {
    if (!pickCenter) return
    change({ center_x: round(x, 4), center_y: round(y, 4) })
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

      <Panel title="Frame" actions={<SkySettingsMenu settings={skyView} onChange={updateSkyView} />} bodyClassName="p-0">
        {frame ? (
          <div className="relative leading-none">
            <img src={frame.imageBlobUrl} alt="Latest frame" className="block h-auto w-full" />
            {skySetup && skyView.on ? (
              <SkyCanvas
                lens={lens}
                latDeg={skySetup.lat}
                lonDeg={skySetup.lon}
                elevationM={skySetup.elevation_m}
                when={new Date(frame.metadata.captured_at)}
                hidden={skyView.hidden}
                maxMagnitude={skyView.maxMagnitude}
                opacity={skyView.opacity}
                interactive
                onPick={pickCenter ? onPick : undefined}
                extraDraw={drawMatches}
              />
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

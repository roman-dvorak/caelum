import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Button,
  Field,
  ImageViewer,
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
import type {
  LensCircleDetection,
  LensConfig,
  LensPairsFit,
  LensProjection,
  LensStarFit,
  LensUnknown,
  StoredFrameInfo,
} from '@caelum/api-client'
import { altAzToFraction } from '@roman-dvorak/caelum-sky'
import { useFrameStream } from '../hooks/useFrameStream.ts'
import { useSkySetup } from '../hooks/useSkySetup.ts'
import { snapToStar } from '../lib/starSnap.ts'
import { localApiClient } from '../services/client.ts'

/** A star the user has matched: where the catalog puts it in the sky, and where it really is in the picture. */
interface Pair {
  key: string
  name: string
  mag: number
  alt: number
  az: number
  /** Frame fractions. */
  x: number
  y: number
}

const UNKNOWNS: { value: LensUnknown; label: string; hint: string }[] = [
  { value: 'roll', label: 'Roll / north', hint: 'turn of the picture about the optical axis' },
  { value: 'tilt', label: 'Camera tilt', hint: 'how far, and which way, the camera leans from the zenith' },
  { value: 'fov', label: 'Field of view', hint: 'how much sky the circle holds' },
  { value: 'center', label: 'Optical centre', hint: 'trades off against tilt — fix it unless it is wrong' },
  { value: 'radius', label: 'Circle radius', hint: 'normally a measurement; fix it' },
]

const PAIR_COLOR = '#7CFC9A'

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
  tilt_deg: 0,
  tilt_azimuth_deg: 0,
}


function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  return sorted.length ? sorted[sorted.length >> 1] : 0
}

const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']

function compass(azimuthDeg: number): string {
  return `${COMPASS[Math.round((((azimuthDeg % 360) + 360) % 360) / 22.5) % 16]} (${(((azimuthDeg % 360) + 360) % 360).toFixed(0)}°)`
}

function round(value: number, digits: number): number {
  const k = 10 ** digits
  return Math.round(value * k) / k
}

export function LensCalibration() {
  const { frame, status: streamStatus } = useFrameStream()

  const [saved, setSaved] = useState<LensConfig | null>(null)
  const [lens, setLens] = useState<LensConfig>(FALLBACK_LENS)
  const [pick, setPick] = useState<'center' | 'edge' | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<{ kind: 'info' | 'error' | 'success'; text: string } | null>(null)
  const [circle, setCircle] = useState<LensCircleDetection | null>(null)
  const [fit, setFit] = useState<LensStarFit | null>(null)
  const skySetup = useSkySetup()
  const [skyView, updateSkyView] = useSkySettings()
  const [overlayEnabled, setOverlayEnabled] = useState<boolean | null>(null)

  // Which picture the lens is calibrated on, and the stars marked on it by hand.
  const [stored, setStored] = useState<{ info: StoredFrameInfo; url: string } | null>(null)
  const [storedPath, setStoredPath] = useState('')
  const [frozen, setFrozen] = useState<{ url: string; time: Date } | null>(null)
  const [marking, setMarking] = useState(true)
  const [snap, setSnap] = useState(true)
  const [pairs, setPairs] = useState<Pair[]>([])
  const [free, setFree] = useState<LensUnknown[]>(['roll', 'tilt', 'fov'])
  const [tryMirror, setTryMirror] = useState(true)
  const [tryProjections, setTryProjections] = useState(false)
  const [pairFit, setPairFit] = useState<LensPairsFit | null>(null)
  const [imageSize, setImageSize] = useState({ width: 4, height: 3 })
  const imgRef = useRef<HTMLImageElement>(null)


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

  // The picture on screen: a stored DNG, a live frame held still for marking, or the newest live frame.
  const shown = useMemo(() => {
    if (stored) {
      return {
        url: stored.url,
        time: new Date(stored.info.captured_at),
        lat: stored.info.lat,
        lon: stored.info.lon,
        elevation: stored.info.elevation_m,
        sensor: { width: stored.info.width, height: stored.info.height },
      }
    }
    const url = frozen?.url ?? frame?.imageBlobUrl
    const time = frozen?.time ?? (frame ? new Date(frame.metadata.captured_at) : null)
    if (!url || !time || !skySetup) return null
    return { url, time, lat: skySetup.lat, lon: skySetup.lon, elevation: skySetup.elevation_m, sensor: null }
  }, [stored, frozen, frame, skySetup])

  const aspect = imageSize.width / imageSize.height
  const pairErrors = useMemo(
    () => (pairFit && pairFit.errors_px.length === pairs.length ? pairFit.errors_px : null),
    [pairFit, pairs.length],
  )

  // Drawn by the sky canvas after the sky: the stars of the last automatic fit, and the stars marked by hand —
  // a line from where the lens puts each one to where it really is.
  const drawMarks = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number) => {
      if (fit) {
        ctx.strokeStyle = PAIR_COLOR
        ctx.lineWidth = 1
        for (const m of fit.matches) {
          ctx.strokeRect((m.x / fit.image_width) * w - 3, (m.y / fit.image_height) * h - 3, 6, 6)
        }
      }
      ctx.lineWidth = 1.5
      pairs.forEach((p, i) => {
        const bad = pairErrors !== null && pairs.length >= 4 && pairErrors[i] > 5 && pairErrors[i] > 3 * median(pairErrors)
        ctx.strokeStyle = bad ? '#ff6e64' : PAIR_COLOR
        const tx = p.x * w
        const ty = p.y * h
        const from = altAzToFraction(lens, w / h, p.alt, p.az)
        if (from) {
          ctx.beginPath()
          ctx.moveTo(from.x * w, from.y * h)
          ctx.lineTo(tx, ty)
          ctx.stroke()
        }
        ctx.beginPath()
        ctx.moveTo(tx - 7, ty)
        ctx.lineTo(tx - 2, ty)
        ctx.moveTo(tx + 2, ty)
        ctx.lineTo(tx + 7, ty)
        ctx.moveTo(tx, ty - 7)
        ctx.lineTo(tx, ty - 2)
        ctx.moveTo(tx, ty + 2)
        ctx.lineTo(tx, ty + 7)
        ctx.stroke()
      })
    },
    [fit, pairs, pairErrors, lens],
  )

  function onPick(x: number, y: number) {
    if (pick === 'center') {
      change({ center_x: round(x, 4), center_y: round(y, 4) })
    } else if (pick === 'edge') {
      // The radius is a fraction of the shorter side; measure in units where the height is 1.
      const distance = Math.hypot((x - lens.center_x) * aspect, y - lens.center_y)
      change({ radius: round(distance / Math.min(aspect, 1), 4) })
    }
    setPick(null)
  }

  // ---- stars marked by hand ----------------------------------------------

  const onStarDrag = useCallback(
    (hit: { kind: string; name: string; mag: number; alt: number; az: number }, x: number, y: number) => {
      const target = (snap && imgRef.current ? snapToStar(imgRef.current, x, y) : null) ?? { x, y }
      const key = `${hit.kind}:${hit.name}`
      // A frame that would be replaced by the next live one is held still: the marks belong to this picture.
      if (!stored && !frozen && frame) void freezeLive()
      setPairs((current) => [
        ...current.filter((p) => p.key !== key),
        { key, name: hit.name, mag: hit.mag, alt: hit.alt, az: hit.az, x: target.x, y: target.y },
      ])
      setPairFit(null)
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [snap, stored, frozen, frame],
  )

  async function freezeLive() {
    if (!frame) return
    const blob = await (await fetch(frame.imageBlobUrl)).blob()
    setFrozen({ url: URL.createObjectURL(blob), time: new Date(frame.metadata.captured_at) })
  }

  function releaseFrozen() {
    setFrozen((current) => {
      if (current) URL.revokeObjectURL(current.url)
      return null
    })
  }

  function backToLive() {
    releaseFrozen()
    setStored(null)
    setPairs([])
    setPairFit(null)
  }

  const loadStored = () =>
    run('stored', async () => {
      const given = storedPath.trim()
      // An https link is fetched by the camera and kept as a stored frame; anything else is a path in the data directory.
      const info = /^https:\/\//i.test(given) ? await localApiClient.fetchRemoteFrame(given) : await localApiClient.getStoredFrame(given)
      releaseFrozen()
      setStored({ info, url: localApiClient.storedFrameImageUrl(info.path) })
      setPairs([])
      setPairFit(null)
      setMessage({
        kind: 'success',
        text: `Loaded ${info.path}, taken ${info.captured_at.replace('T', ' ').slice(0, 19)} UTC at ${info.lat.toFixed(3)}°, ${info.lon.toFixed(3)}°.`,
      })
    })

  const solvePairs = () =>
    run('pairs', async () => {
      const result = await localApiClient.fitLensFromPairs({
        lens,
        pairs: pairs.map((p) => ({ alt_deg: p.alt, az_deg: p.az, x: p.x, y: p.y })),
        free,
        try_mirror: tryMirror,
        projections: tryProjections ? PROJECTIONS.map((p) => p.value) : undefined,
        image_width: shown?.sensor?.width ?? imageSize.width,
        image_height: shown?.sensor?.height ?? imageSize.height,
      })
      setLens(result.lens)
      setPairFit(result)
      // One star marked on its neighbour drags the whole solution: name the one that sits furthest from its place.
      const worst = result.errors_px.reduce((best, e, i) => (e > result.errors_px[best] ? i : best), 0)
      const suspect =
        pairs.length >= 4 && result.errors_px[worst] > 3 * median(result.errors_px) && result.errors_px[worst] > 5 ? pairs[worst] : null
      setMessage({
        kind: suspect ? 'info' : 'success',
        text:
          `Solved from ${pairs.length} stars: residual ${result.rms_px.toFixed(2)} px RMS` +
          (result.lens.tilt_deg ? `, camera tilted ${result.lens.tilt_deg.toFixed(2)}° towards ${compass(result.lens.tilt_azimuth_deg ?? 0)}` : '') +
          (suspect
            ? `. ${suspect.name} is ${result.errors_px[worst].toFixed(0)} px off — it may be marked on the wrong star (red line); remove it and solve again.`
            : '.'),
      })
    })

  const removePair = (key: string) => {
    setPairs((current) => current.filter((p) => p.key !== key))
    setPairFit(null)
  }

  const toggleFree = (value: LensUnknown) =>
    setFree((current) => (current.includes(value) ? current.filter((v) => v !== value) : [...current, value]))

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
          <div className="flex items-center gap-3">
            {stored ? (
              <StatusBadge>Stored: {stored.info.path.split('/').pop()}</StatusBadge>
            ) : frozen ? (
              <StatusBadge tone="live">Held still</StatusBadge>
            ) : null}
            {stored || frozen ? (
              <Button variant="ghost" onClick={backToLive}>
                Back to live
              </Button>
            ) : (
              <Button variant="ghost" onClick={() => void freezeLive()} disabled={!frame}>
                Hold this frame
              </Button>
            )}
            <SkySettingsMenu settings={skyView} onChange={updateSkyView} />
          </div>
        }
        bodyClassName="p-0"
      >
        {shown ? (
          <ImageViewer
            src={shown.url}
            alt="Frame to calibrate on"
            imgRef={imgRef}
            zoomable
            onImageLoad={(img) => setImageSize({ width: img.naturalWidth, height: img.naturalHeight })}
          >
            {skySetup && skyView.on ? (
              <SkyCanvas
                lens={lens}
                latDeg={shown.lat}
                lonDeg={shown.lon}
                elevationM={shown.elevation}
                when={shown.time}
                hidden={skyView.hidden}
                maxMagnitude={skyView.maxMagnitude}
                opacity={skyView.opacity}
                interactive
                onPick={pick ? onPick : undefined}
                onStarDrag={marking ? onStarDrag : undefined}
                extraDraw={drawMarks}
              />
            ) : null}
          </ImageViewer>
        ) : (
          <div className="flex aspect-video items-center justify-center text-sm text-ink-muted">
            {streamStatus === 'connecting' ? 'Connecting to live stream…' : 'Waiting for first frame…'}
          </div>
        )}
      </Panel>

      <Panel title="Mark stars by hand">
        <div className="flex flex-col gap-4">
          <p className="text-sm text-ink-muted">
            When the automatic fit has nothing to work with — the Moon is up, there is cloud, or the camera is not looking straight up — match stars
            yourself. <strong className="font-medium text-ink">Grab the ring of a star and drag it onto the real star</strong> in the picture (it
            snaps to the star’s centre); do that for five or more stars spread over the whole sky, then <strong className="font-medium text-ink">Solve</strong>.
            The first mark holds the frame still, so the marks stay on the picture you made them on. The lens fitted from them also gets the camera’s tilt.
          </p>
          <div className="flex flex-wrap items-end gap-6">
            <label className="flex items-center gap-2 text-sm text-ink select-none">
              <input type="checkbox" checked={marking} onChange={(e) => setMarking(e.target.checked)} className="accent-amber" />
              Dragging marks stars
            </label>
            <label className="flex items-center gap-2 text-sm text-ink select-none">
              <input type="checkbox" checked={snap} onChange={(e) => setSnap(e.target.checked)} className="accent-amber" />
              Snap to the star under the pointer
            </label>
            <label className="flex items-center gap-2 text-sm text-ink select-none" title="Solve once for each of the four projections and keep the one the stars fit best">
              <input type="checkbox" checked={tryProjections} onChange={(e) => setTryProjections(e.target.checked)} className="accent-amber" />
              Find the best projection
            </label>
            <label className="flex items-center gap-2 text-sm text-ink select-none">
              <input type="checkbox" checked={tryMirror} onChange={(e) => setTryMirror(e.target.checked)} className="accent-amber" />
              Try both handednesses (east/west)
            </label>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            <span className="text-sm text-ink-muted">Solve for:</span>
            {UNKNOWNS.map((u) => (
              <label key={u.value} title={u.hint} className="flex items-center gap-2 text-sm text-ink select-none">
                <input type="checkbox" checked={free.includes(u.value)} onChange={() => toggleFree(u.value)} className="accent-amber" />
                {u.label}
              </label>
            ))}
          </div>
          <div className="flex flex-wrap gap-3">
            <Button variant="primary" onClick={() => void solvePairs()} disabled={busy !== null || pairs.length < 2 || free.length === 0}>
              {busy === 'pairs' ? 'Solving…' : `Solve from ${pairs.length} star${pairs.length === 1 ? '' : 's'}`}
            </Button>
            <Button onClick={() => { setPairs((c) => c.slice(0, -1)); setPairFit(null) }} disabled={pairs.length === 0}>
              Undo last
            </Button>
            <Button variant="ghost" onClick={() => { setPairs([]); setPairFit(null) }} disabled={pairs.length === 0}>
              Clear marks
            </Button>
          </div>
          {pairFit ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Readout label="Residual (RMS)" value={`${pairFit.rms_px.toFixed(2)} px`} />
              <Readout label="Stars / unknowns" value={`${pairs.length} / ${pairFit.parameters}`} />
              <Readout label="Camera tilt" value={`${(pairFit.lens.tilt_deg ?? 0).toFixed(2)}°`} />
              <Readout label="Leaning towards" value={pairFit.lens.tilt_deg ? compass(pairFit.lens.tilt_azimuth_deg ?? 0) : '—'} />
              {Object.keys(pairFit.by_projection).length > 0 ? (
                <Readout
                  label="Projections (RMS px)"
                  value={Object.entries(pairFit.by_projection)
                    .map(([name, rms]) => `${name.replace('_fisheye', '')} ${rms.toFixed(1)}`)
                    .join(' · ')}
                />
              ) : null}
            </div>
          ) : null}
          {pairs.length > 0 ? (
            <ul className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-3">
              {pairs.map((p, i) => (
                <li key={p.key} className="flex items-center justify-between gap-2 border-b border-border-subtle py-1">
                  <span className="text-ink">
                    {p.name} <span className="text-ink-muted">· mag {p.mag.toFixed(1)}</span>
                  </span>
                  <span className="flex items-center gap-3">
                    {pairErrors ? <span className="text-ink-muted tabular-nums">{pairErrors[i].toFixed(1)} px</span> : null}
                    <button type="button" className="text-ink-muted hover:text-ink" aria-label={`Remove ${p.name}`} onClick={() => removePair(p.key)}>
                      ✕
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </Panel>

      <Panel title="Stored frame">
        <div className="flex flex-col gap-3">
          <p className="text-sm text-ink-muted">
            Calibrate on a frame from the archive instead of the live view — for example a good night’s DNG. Its time and the camera’s position are
            read from the file. Give the path relative to the data directory, e.g. <code>raw/2026/10/30/20261030-004840.dng</code>, or an{' '}
            <code>https://</code> link to a DNG (the remote archive): the camera downloads it once and keeps the copy in <code>lens-frames/</code>.
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <input
              type="text"
              value={storedPath}
              onChange={(e) => setStoredPath(e.target.value)}
              placeholder="raw/YYYY/MM/DD/…dng  or  https://…/frame.dng"
              className={`${inputClass} w-full max-w-xl font-mono`}
            />
            <Button onClick={() => void loadStored()} disabled={busy !== null || storedPath.trim() === ''}>
              {busy === 'stored' ? 'Loading…' : 'Load frame'}
            </Button>
          </div>
        </div>
      </Panel>

      <Panel title="Find it automatically">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-3">
            <Button variant="primary" onClick={() => void detectCircle()} disabled={busy !== null || !frame || stored !== null}>
              {busy === 'circle' ? 'Detecting…' : 'Detect image circle'}
            </Button>
            <Button variant="primary" onClick={() => void fitStars(true)} disabled={busy !== null || !frame || stored !== null}>
              {busy === 'stars' ? 'Fitting… (up to a minute)' : 'Fit from stars'}
            </Button>
            <Button onClick={() => void fitStars(false)} disabled={busy !== null || !frame || stored !== null}>
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
            <Field label="North offset (°)" hint="Roll of the picture about the optical axis (against north when looking up)">
              {number('azimuth_offset_deg', 0.5, -360, 360, 2)}
            </Field>
            <Field label="Camera tilt (°)" hint="How far the axis leans from the zenith (0 = straight up)">
              {number('tilt_deg', 0.1, 0, 60, 2)}
            </Field>
            <Field label="Tilted towards (°)" hint="Compass azimuth of the lean: 0 N, 90 E, 180 S, 270 W">
              {number('tilt_azimuth_deg', 1, 0, 360, 1)}
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
            <Button variant={pick === 'center' ? 'primary' : 'secondary'} onClick={() => setPick((v) => (v === 'center' ? null : 'center'))} disabled={!shown}>
              {pick === 'center' ? 'Click the centre on the image…' : 'Pick centre on image'}
            </Button>
            <Button variant={pick === 'edge' ? 'primary' : 'secondary'} onClick={() => setPick((v) => (v === 'edge' ? null : 'edge'))} disabled={!shown}>
              {pick === 'edge' ? 'Click the edge of the circle…' : 'Pick circle edge on image'}
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

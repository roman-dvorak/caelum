import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import type { CameraManifest, DateIndex } from '@caelum/api-client'
import { DateStrip, KeogramStrip, Message, OverlayToggle, SkySettingsMenu, useSkySettings } from '@caelum/ui'
import { GalleryItem, type SkyView } from '../components/GalleryItem.tsx'
import { useCameraManifest } from '../hooks/useCameraManifest.ts'
import { useDateIndex } from '../hooks/useDateIndex.ts'
import { remoteApiClient } from '../services/client.ts'

export function CameraDetail() {
  const { slug = '' } = useParams<{ slug: string }>()
  // Remount the view whenever the route's slug changes, so date-selection
  // state doesn't leak between cameras instead of resetting via an effect.
  return <CameraDetailView key={slug} slug={slug} />
}

function CameraDetailView({ slug }: { slug: string }) {
  const { manifest, error: manifestError, loading: manifestLoading } = useCameraManifest(slug)
  const [userSelectedDate, setUserSelectedDate] = useState<string | null>(null)

  const latestDate = useMemo(() => {
    if (!manifest || manifest.dates.length === 0) return null
    return [...manifest.dates].sort((a, b) => b.date.localeCompare(a.date))[0].date
  }, [manifest])

  // Default to the most recent date until the user explicitly picks one —
  // computed at render time rather than synced via an effect.
  const selectedDate = userSelectedDate ?? latestDate

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Link to="/" className="text-sm font-medium text-sky hover:underline">
          ← Cameras
        </Link>
      </div>

      {manifestLoading && <p className="text-sm text-ink-muted">Loading camera…</p>}
      {manifestError && (
        <Message kind="error">{manifestError}</Message>
      )}

      {manifest && (
        <>
          <div>
            <h1 className="text-lg font-semibold text-ink">{manifest.name}</h1>
            <p className="font-mono text-xs text-ink-muted">
              {[
                manifest.slug,
                manifest.observatory_name,
                manifest.camera_type,
                manifest.owner,
                manifest.location ? `${manifest.location.lat.toFixed(4)}, ${manifest.location.lon.toFixed(4)}` : '',
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </div>

          <DateStrip dates={manifest.dates} selectedDate={selectedDate} onSelect={setUserSelectedDate} />

          {selectedDate ? (
            // Keyed by date: switching dates remounts this whole subtree,
            // so its data-fetching hook always starts fresh with no extra
            // reset effect needed.
            <DateGallery key={selectedDate} slug={slug} date={selectedDate} manifest={manifest} />
          ) : null}
        </>
      )}
    </div>
  )
}

function DateGallery({ slug, date, manifest }: { slug: string; date: string; manifest: CameraManifest }) {
  const { dateIndex, error, loading } = useDateIndex(slug, date)

  return (
    <div className="flex flex-col gap-4">
      <KeogramStrip src={remoteApiClient.keogramUrl(slug, date)} date={date} />

      {loading && <p className="text-sm text-ink-muted">Loading frames…</p>}
      {error && <Message kind="error">{error}</Message>}

      {dateIndex ? <Gallery slug={slug} dateIndex={dateIndex} manifest={manifest} /> : null}
    </div>
  )
}

function Gallery({ slug, dateIndex, manifest }: { slug: string; dateIndex: DateIndex; manifest: CameraManifest }) {
  const [showOverlay, setShowOverlay] = useState(true)
  const [skyView, updateSkyView] = useSkySettings()
  const hasOverlays = dateIndex.images.some((image) => image.overlay)
  // The sky can be drawn here only when the camera published where it is.
  const sky: SkyView | undefined =
    manifest.sky && manifest.location
      ? { lens: manifest.sky.lens, lat: manifest.location.lat, lon: manifest.location.lon, hidden: skyView.hidden, maxMagnitude: skyView.maxMagnitude }
      : undefined

  return (
    <div className="flex flex-col gap-2">
      {hasOverlays || sky ? (
        <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-1">
          {sky ? <SkySettingsMenu settings={skyView} onChange={updateSkyView} /> : null}
          {hasOverlays ? <OverlayToggle checked={showOverlay} onChange={setShowOverlay} /> : null}
        </div>
      ) : null}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {dateIndex.images.map((image) => (
          <GalleryItem
            key={image.time}
            slug={slug}
            time={image.time}
            thumbnailPath={image.thumbnail}
            overlayPath={image.overlay}
            showOverlay={showOverlay}
            sky={sky}
          />
        ))}
      </div>
    </div>
  )
}

import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import type { DateIndex } from '@caelum/api-client'
import { DateStrip, KeogramStrip, LayerToggles, Message, OverlayToggle, useHiddenLayers } from '@caelum/ui'
import { GalleryItem } from '../components/GalleryItem.tsx'
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
            <DateGallery key={selectedDate} slug={slug} date={selectedDate} layers={manifest.sky?.layers ?? []} />
          ) : null}
        </>
      )}
    </div>
  )
}

function DateGallery({ slug, date, layers }: { slug: string; date: string; layers: string[] }) {
  const { dateIndex, error, loading } = useDateIndex(slug, date)

  return (
    <div className="flex flex-col gap-4">
      <KeogramStrip src={remoteApiClient.keogramUrl(slug, date)} date={date} />

      {loading && <p className="text-sm text-ink-muted">Loading frames…</p>}
      {error && <Message kind="error">{error}</Message>}

      {dateIndex ? <Gallery slug={slug} dateIndex={dateIndex} layers={layers} /> : null}
    </div>
  )
}

function Gallery({ slug, dateIndex, layers }: { slug: string; dateIndex: DateIndex; layers: string[] }) {
  const [showOverlay, setShowOverlay] = useState(true)
  const [hidden, setLayerVisible] = useHiddenLayers('caelum.hiddenLayers')
  const present = layers.filter((layer) => dateIndex.images.some((image) => image.layers?.[layer]))
  const hasOverlays = dateIndex.images.some((image) => image.overlay) || present.length > 0

  return (
    <div className="flex flex-col gap-2">
      {hasOverlays ? (
        <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-1">
          <LayerToggles layers={present} hidden={hidden} onChange={setLayerVisible} />
          <OverlayToggle checked={showOverlay} onChange={setShowOverlay} />
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
            layerPaths={present.filter((layer) => !hidden.has(layer)).flatMap((layer) => image.layers?.[layer] ?? [])}
            showOverlay={showOverlay}
          />
        ))}
      </div>
    </div>
  )
}

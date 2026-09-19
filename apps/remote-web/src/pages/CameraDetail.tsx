import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import type { DateIndex } from '@caelum/api-client'
import { DateStrip, KeogramStrip } from '@caelum/ui'
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
        <Link to="/" className="text-sm text-slate-400 hover:text-slate-200">
          ← Cameras
        </Link>
      </div>

      {manifestLoading && <p className="text-sm text-slate-500">Loading camera…</p>}
      {manifestError && (
        <p className="rounded-md border border-red-900 bg-red-950/60 px-3 py-2 text-sm text-red-300">
          {manifestError}
        </p>
      )}

      {manifest && (
        <>
          <div>
            <h1 className="text-lg font-semibold text-slate-100">{manifest.name}</h1>
            <p className="text-xs text-slate-500">
              {manifest.slug} · {manifest.location.lat.toFixed(4)}, {manifest.location.lon.toFixed(4)}
            </p>
          </div>

          <DateStrip dates={manifest.dates} selectedDate={selectedDate} onSelect={setUserSelectedDate} />

          {selectedDate ? (
            // Keyed by date: switching dates remounts this whole subtree,
            // so its data-fetching hook always starts fresh with no extra
            // reset effect needed.
            <DateGallery key={selectedDate} slug={slug} date={selectedDate} />
          ) : null}
        </>
      )}
    </div>
  )
}

function DateGallery({ slug, date }: { slug: string; date: string }) {
  const { dateIndex, error, loading } = useDateIndex(slug, date)

  return (
    <div className="flex flex-col gap-4">
      <KeogramStrip src={remoteApiClient.keogramUrl(slug, date)} date={date} />

      {loading && <p className="text-sm text-slate-500">Loading frames…</p>}
      {error && (
        <p className="rounded-md border border-red-900 bg-red-950/60 px-3 py-2 text-sm text-red-300">{error}</p>
      )}

      {dateIndex ? <Gallery slug={slug} dateIndex={dateIndex} /> : null}
    </div>
  )
}

function Gallery({ slug, dateIndex }: { slug: string; dateIndex: DateIndex }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {dateIndex.images.map((image) => (
        <GalleryItem
          key={image.time}
          slug={slug}
          time={image.time}
          thumbnailPath={image.thumbnail}
          metadataPath={image.metadata}
        />
      ))}
    </div>
  )
}

import { useCallback, useEffect, useState } from 'react'
import type {
  DerivativeEntry,
  DerivativeKindSummary,
  FrameDateSummary,
  FrameEntry,
  FrameListResponse,
} from '@caelum/api-client'
import {
  Button,
  Calendar,
  EmptyState,
  Lightbox,
  Loading,
  Message,
  OverlayToggle,
  PageHeader,
  Panel,
  Readout,
  RefreshIcon,
  TrashIcon,
  formatBytes,
  formatCaptureTime,
  formatSiteTime,
} from '@caelum/ui'
import type { LightboxItem } from '@caelum/ui'
import { useAuth } from '../authContext.ts'
import { localApiClient } from '../services/client.ts'

type GroupMode = 'night' | 'date'
type View = 'captures' | 'derivatives'
const PAGE_SIZE = 60

/**
 * The recordings manager: the capture archive as a time series rather than
 * as directories. One row per capture, with its thumbnail, sidecar and raw
 * frame collapsed together, plus the bulk deletes that actually reclaim
 * space — a night of raw frames is gigabytes, and deleting it one file at a
 * time through the file browser is not a real option.
 *
 * Two groupings, picked with the toggle below:
 * - **Observation day** (default) — from one `observation_day.start`
 *   (sunrise, or a fixed local time) to the next, labelled by the local date
 *   it started on. A session that runs past midnight stays one entry
 *   instead of splitting in two; the keogram uses the same days.
 * - **Date (UTC)** — the on-disk calendar date, useful for cross-referencing
 *   the raw directory tree or the remote gallery, which both use it.
 *
 * Every timestamp from the API is UTC; `timezone` (from `/api/status`) is
 * what every displayed time gets converted to and labelled with, so it is
 * never a guess which zone a given clock reading is in.
 */
export function Frames() {
  const { isAdmin } = useAuth()
  const [mode, setMode] = useState<GroupMode>('night')
  const [timezone, setTimezone] = useState<string | null>(null)
  const [summaries, setSummaries] = useState<FrameDateSummary[] | null>(null)
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)
  const reload = useCallback(async () => setReloadToken((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false
    localApiClient
      .getStatus()
      .then((status) => {
        if (!cancelled) setTimezone(status.timezone)
      })
      .catch(() => undefined) // non-fatal: falls back to showing raw UTC only
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    async function run() {
      try {
        const result =
          mode === 'night' ? await localApiClient.listObservationNights() : await localApiClient.listFrameDates()
        if (cancelled) return
        setSummaries(result)
        setSelectedLabel(result[0]?.date ?? null)
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      }
    }

    void run()
    return () => {
      cancelled = true
    }
    // Switching mode picks a fresh default selection rather than trying to
    // carry a UTC date into night-mode's different labelling or vice versa.
  }, [mode, reloadToken])

  async function deleteWholePeriod(utcDates: string[]) {
    const what = mode === 'night' ? 'night' : 'date'
    if (!window.confirm(`Delete every file captured this ${what}? This cannot be undone.`)) return
    try {
      for (const utcDate of utcDates) {
        await localApiClient.deleteFrames({ date: utcDate })
      }
      setSelectedLabel(null)
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <>
      <PageHeader
        title="Recordings"
        description="Captured frames, with the raw files and derivatives that belong to each."
        actions={
          <>
            <div className="flex border border-line text-xs">
              {(['night', 'date'] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setMode(option)}
                  className={[
                    'px-3 py-1.5 tracking-wide uppercase transition',
                    mode === option ? 'bg-amber text-void font-semibold' : 'text-ink-dim hover:text-ink',
                  ].join(' ')}
                >
                  {option === 'night' ? 'Observation day' : 'Date (UTC)'}
                </button>
              ))}
            </div>
            <Button icon={<RefreshIcon size={14} />} onClick={() => void reload()}>
              Refresh
            </Button>
          </>
        }
      />

      {error ? <Message kind="error">{error}</Message> : null}

      {summaries === null ? (
        <Loading />
      ) : summaries.length === 0 ? (
        <EmptyState>Nothing recorded yet.</EmptyState>
      ) : (
        <div className="flex flex-col gap-4">
          <Calendar
            entries={summaries.map((s) => ({ date: s.date, count: s.thumbnails }))}
            selected={selectedLabel}
            onSelect={setSelectedLabel}
          />
          {selectedLabel ? (
            (() => {
              const summary = summaries.find((s) => s.date === selectedLabel)
              return summary ? (
                <p className="font-mono text-xs text-ink-faint tabular-nums">
                  {summary.thumbnails} frames · {summary.raws} raw · {formatBytes(summary.total_bytes)}
                </p>
              ) : null
            })()
          ) : null}

          {selectedLabel ? (
            <PeriodDetail
              key={`${mode}:${selectedLabel}`}
              mode={mode}
              label={selectedLabel}
              timezone={timezone}
              isAdmin={isAdmin}
              onDeleteWholePeriod={deleteWholePeriod}
              onChanged={reload}
            />
          ) : null}
        </div>
      )}
    </>
  )
}

function PeriodDetail({
  mode,
  label,
  timezone,
  isAdmin,
  onDeleteWholePeriod,
  onChanged,
}: {
  mode: GroupMode
  label: string
  timezone: string | null
  isAdmin: boolean
  onDeleteWholePeriod: (utcDates: string[]) => void
  onChanged: () => Promise<void>
}) {
  const [view, setView] = useState<View>('captures')

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2">
        {(['captures', 'derivatives'] as const).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setView(option)}
            className={[
              'border px-3 py-1.5 text-xs font-semibold tracking-wide uppercase transition',
              view === option ? 'border-amber bg-amber/10 text-amber' : 'border-line text-ink-dim hover:border-amber-dim',
            ].join(' ')}
          >
            {option === 'captures' ? 'Captures' : 'Derivatives'}
          </button>
        ))}
      </div>

      {view === 'captures' ? (
        <CapturesGallery
          mode={mode}
          label={label}
          timezone={timezone}
          isAdmin={isAdmin}
          onDeleteWholePeriod={onDeleteWholePeriod}
          onChanged={onChanged}
        />
      ) : (
        <DerivativesGallery mode={mode} label={label} />
      )}
    </div>
  )
}

function CapturesGallery({
  mode,
  label,
  timezone,
  isAdmin,
  onDeleteWholePeriod,
  onChanged,
}: {
  mode: GroupMode
  label: string
  timezone: string | null
  isAdmin: boolean
  onDeleteWholePeriod: (utcDates: string[]) => void
  onChanged: () => Promise<void>
}) {
  const [listing, setListing] = useState<FrameListResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selection, setSelection] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [page, setPage] = useState(0)
  const [showOverlay, setShowOverlay] = useState(true)
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null)

  const [reloadToken, setReloadToken] = useState(0)
  const reload = useCallback(async () => setReloadToken((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false

    async function run() {
      try {
        const params = {
          [mode]: label,
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        } as Parameters<typeof localApiClient.listFrames>[0]
        const next = await localApiClient.listFrames(params)
        if (cancelled) return
        setListing(next)
        setSelection(new Set())
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [mode, label, page, reloadToken])

  function toggle(time: string) {
    setSelection((current) => {
      const next = new Set(current)
      if (!next.delete(time)) next.add(time)
      return next
    })
  }

  async function deleteSelection() {
    if (selection.size === 0) return
    if (!window.confirm(`Delete ${selection.size} capture(s)?`)) return
    setBusy(true)
    try {
      // Each stem carries its own UTC date, so this deletes correctly even
      // when the selection spans two dates (a night crossing midnight).
      await localApiClient.deleteFrames({ times: [...selection] })
      await reload()
      await onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  /** Delete only the raw FITS files on the *currently loaded page*, keeping
   * thumbnails and metadata — the usual way to reclaim most of a night's
   * space without losing the record that it happened. Scoped to the page
   * (not the whole period) so it doesn't silently touch more than what's
   * on screen when the listing is paginated. */
  async function deleteRawOnlyOnPage() {
    const stemsWithRaw = (listing?.frames ?? []).filter((f) => f.raw).map((f) => f.time)
    if (stemsWithRaw.length === 0) return
    if (!window.confirm(`Delete ${stemsWithRaw.length} raw frame(s) on this page, keeping thumbnails?`)) return
    setBusy(true)
    try {
      await localApiClient.deleteFrames({ times: stemsWithRaw, kinds: ['raw'] })
      await reload()
      await onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (error) return <Message kind="error">{error}</Message>
  if (!listing) return <Loading />

  const pageCount = Math.max(1, Math.ceil(listing.total_frames / PAGE_SIZE))
  const currentPage = Math.floor(listing.offset / PAGE_SIZE)
  const rangeStart = listing.total_frames === 0 ? 0 : listing.offset + 1
  const rangeEnd = Math.min(listing.offset + listing.frames.length, listing.total_frames)
  const totalRaws = listing.frames.filter((f) => f.raw).length
  const totalBytes = listing.frames.reduce((sum, f) => sum + f.total_bytes, 0)

  const lightboxItems: LightboxItem[] = listing.frames.map((frame) => ({
    src: frameImageUrl(frame) ?? '',
    overlaySrc: showOverlay ? frameOverlayUrl(frame) : null,
    caption: <FrameCaption frame={frame} timezone={timezone} />,
  }))
  const hasOverlays = listing.frames.some((frame) => frame.overlay)

  return (
    <div className="flex flex-col gap-4">
      <Panel
        title={mode === 'night' ? `Observation day ${label}` : label}
        actions={
          isAdmin ? (
            <>
              <Button
                variant="danger"
                icon={<TrashIcon size={14} />}
                disabled={busy || selection.size === 0}
                onClick={() => void deleteSelection()}
              >
                Delete {selection.size || ''} selected
              </Button>
              <Button variant="danger" disabled={busy || totalRaws === 0} onClick={() => void deleteRawOnlyOnPage()}>
                Delete raw on page
              </Button>
              <Button
                variant="danger"
                icon={<TrashIcon size={14} />}
                disabled={busy}
                onClick={() => onDeleteWholePeriod(listing.utc_dates)}
              >
                Delete {mode === 'night' ? 'night' : 'date'}
              </Button>
            </>
          ) : null
        }
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Readout label="Captures (page)" value={listing.frames.length} />
          <Readout label="Total captures" value={listing.total_frames} />
          <Readout label="Raw on page" value={totalRaws} />
          <Readout label="Page size" value={formatBytes(totalBytes)} />
        </div>
        {hasOverlays ? (
          <div className="mt-3 flex justify-end">
            <OverlayToggle checked={showOverlay} onChange={setShowOverlay} />
          </div>
        ) : null}
      </Panel>

      {listing.frames.length === 0 ? (
        <EmptyState>No captures on this page.</EmptyState>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {listing.frames.map((frame, index) => (
            <FrameTile
              key={frame.time}
              frame={frame}
              selected={selection.has(frame.time)}
              selectable={isAdmin}
              showOverlay={showOverlay}
              onToggle={() => toggle(frame.time)}
              onOpen={() => setLightboxIndex(index)}
            />
          ))}
        </div>
      )}

      {listing.total_frames > PAGE_SIZE ? (
        <div className="flex items-center justify-between gap-3 border-t border-line-soft pt-3">
          <span className="font-mono text-xs text-ink-faint tabular-nums">
            {rangeStart}–{rangeEnd} of {listing.total_frames}
          </span>
          <div className="flex items-center gap-2">
            <Button disabled={currentPage === 0} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <span className="font-mono text-xs text-ink-faint tabular-nums">
              Page {currentPage + 1} / {pageCount}
            </span>
            <Button disabled={currentPage + 1 >= pageCount} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </div>
        </div>
      ) : null}

      {lightboxIndex !== null ? (
        <Lightbox
          items={lightboxItems}
          index={lightboxIndex}
          onIndexChange={setLightboxIndex}
          onClose={() => setLightboxIndex(null)}
        />
      ) : null}
    </div>
  )
}

/** The camera-rendered overlay to stack over the thumbnail, when stored
 * as a separate file (not for a raw-preview fallback, whose size differs). */
function frameOverlayUrl(frame: FrameEntry): string | null {
  return frame.thumbnail && frame.overlay ? localApiClient.fileContentUrl(frame.overlay) : null
}

/** Prefer the thumbnail; fall back to a rendered raw preview for captures
 * whose thumbnail has already been rotated away by retention. */
function frameImageUrl(frame: FrameEntry): string | null {
  return frame.thumbnail
    ? localApiClient.fileContentUrl(frame.thumbnail)
    : frame.raw
      ? localApiClient.filePreviewUrl(frame.raw, 1600)
      : null
}

/** One availability chip. Present parts are links to the actual file;
 * missing ones stay visible but struck through, because "this capture has no
 * raw" is itself the information you came to the page for — a chip that
 * simply vanished would be indistinguishable from a layout quirk. */
function AssetChip({ label, path, title }: { label: string; path: string | null; title: string }) {
  const className = 'px-1 py-0.5 font-mono text-[0.6rem] tracking-wide border transition'

  if (!path) {
    return (
      <span
        title={`No ${title} for this capture`}
        className={`${className} border-line-soft text-ink-faint line-through decoration-ink-faint/60`}
      >
        {label}
      </span>
    )
  }
  return (
    <a
      href={localApiClient.fileContentUrl(path, true)}
      title={`Download ${title}`}
      className={`${className} border-cyan-dim text-cyan hover:border-cyan hover:bg-cyan/10`}
    >
      {label}
    </a>
  )
}

/** Everything that used to live in the grid tile's caption now lives in the
 * lightbox instead — the grid itself shows only the image (see `FrameTile`). */
function FrameCaption({ frame, timezone }: { frame: FrameEntry; timezone: string | null }) {
  const site = timezone ? formatSiteTime(frame.captured_at, timezone) : null
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <span className="tabular-nums" title={formatCaptureTime(frame.time)}>
        {site ? `${site.clock} ${site.zone}` : formatCaptureTime(frame.time)}
      </span>
      <div className="flex items-center gap-1">
        <AssetChip label="IMG" path={frame.thumbnail} title="thumbnail" />
        <AssetChip label="RAW" path={frame.raw} title="raw FITS frame" />
        <AssetChip label="JSON" path={frame.metadata} title="metadata sidecar" />
      </div>
      <span className="tabular-nums">{formatBytes(frame.total_bytes)}</span>
    </div>
  )
}

function FrameTile({
  frame,
  selected,
  selectable,
  showOverlay,
  onToggle,
  onOpen,
}: {
  frame: FrameEntry
  selected: boolean
  selectable: boolean
  showOverlay: boolean
  onToggle: () => void
  onOpen: () => void
}) {
  const imageUrl = frameImageUrl(frame)
  const overlayUrl = showOverlay ? frameOverlayUrl(frame) : null

  return (
    <div className={['relative overflow-hidden border transition', selected ? 'border-amber' : 'border-line'].join(' ')}>
      <button type="button" onClick={onOpen} className="block aspect-4/3 w-full bg-void">
        {imageUrl ? (
          <span className="relative block h-full w-full">
            <img src={imageUrl} alt={frame.time} loading="lazy" className="h-full w-full object-cover" />
            {overlayUrl ? (
              <img
                src={overlayUrl}
                alt=""
                aria-hidden
                loading="lazy"
                className="pointer-events-none absolute inset-0 h-full w-full object-cover"
              />
            ) : null}
          </span>
        ) : (
          <span className="flex h-full items-center justify-center text-xs text-ink-faint">no image</span>
        )}
      </button>
      {selectable ? (
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          onClick={(e) => e.stopPropagation()}
          aria-label={`Select capture ${frame.time}`}
          className="absolute top-2 left-2 z-10 h-4 w-4 accent-amber"
        />
      ) : null}
    </div>
  )
}

function DerivativesGallery({ mode, label }: { mode: GroupMode; label: string }) {
  const [kinds, setKinds] = useState<DerivativeKindSummary[] | null>(null)
  const [kind, setKind] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const params = { [mode]: label } as Parameters<typeof localApiClient.listDerivativeKinds>[0]
    localApiClient
      .listDerivativeKinds(params)
      .then((next) => {
        if (cancelled) return
        setKinds(next)
        setKind((current) => (current && next.some((k) => k.kind === current) ? current : (next[0]?.kind ?? null)))
        setError(null)
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : String(err)))
    return () => {
      cancelled = true
    }
  }, [mode, label])

  if (error) return <Message kind="error">{error}</Message>
  if (kinds === null) return <Loading />
  if (kinds.length === 0) return <EmptyState>No derivatives for this period yet.</EmptyState>

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2 overflow-x-auto pb-1">
        {kinds.map((k) => (
          <button
            key={k.kind}
            type="button"
            onClick={() => setKind(k.kind)}
            className={[
              'shrink-0 border px-3 py-1.5 font-mono text-xs transition',
              k.kind === kind
                ? 'border-amber bg-amber/8 text-amber'
                : 'border-line text-ink-dim hover:border-amber-dim hover:text-ink',
            ].join(' ')}
          >
            {k.kind} ({k.count})
          </button>
        ))}
      </div>

      {/* Keyed by kind so switching tabs remounts fresh (page/listing reset
          for free) instead of resetting that state manually in an effect. */}
      {kind ? <DerivativeKindGallery key={kind} mode={mode} label={label} kind={kind} /> : null}
    </div>
  )
}

function DerivativeKindGallery({ mode, label, kind }: { mode: GroupMode; label: string; kind: string }) {
  const [listing, setListing] = useState<{ entries: DerivativeEntry[]; total: number; offset: number } | null>(null)
  const [page, setPage] = useState(0)
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const params = {
      [mode]: label,
      kind,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    } as Parameters<typeof localApiClient.listDerivatives>[0]
    localApiClient
      .listDerivatives(params)
      .then((next) => {
        if (!cancelled) setListing(next)
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : String(err)))
    return () => {
      cancelled = true
    }
  }, [mode, label, kind, page])

  if (error) return <Message kind="error">{error}</Message>
  if (!listing) return <Loading />

  const pageCount = Math.max(1, Math.ceil(listing.total / PAGE_SIZE))
  const currentPage = Math.floor(listing.offset / PAGE_SIZE)

  const lightboxItems: LightboxItem[] = listing.entries.map((entry) => ({
    src: `${localApiClient.fileContentUrl(entry.full)}${cacheKey(entry)}`,
    caption: (
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="tabular-nums">{formatCaptureTime(entry.stem)}</span>
        <span className="tabular-nums">{formatBytes(entry.size)}</span>
      </div>
    ),
  }))

  return (
    <div className="flex flex-col gap-4">
      {listing.entries.length === 0 ? (
        <EmptyState>No derivatives on this page.</EmptyState>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {listing.entries.map((entry, index) => (
            <button
              key={entry.stem}
              type="button"
              onClick={() => setLightboxIndex(index)}
              className="aspect-square overflow-hidden border border-line bg-void"
            >
              <img
                // The day's keogram is one file rewritten as the night goes
                // on: key the URL on its size so the browser shows the
                // current version, not a cached earlier one.
                src={`${localApiClient.fileContentUrl(entry.thumbnail ?? entry.full)}${cacheKey(entry)}`}
                alt={entry.stem}
                loading="lazy"
                // A keogram is a long thin strip — shown whole, not cropped.
                className={`h-full w-full ${kind.startsWith('keogram') ? 'object-contain' : 'object-cover'}`}
              />
            </button>
          ))}
        </div>
      )}

      {listing.total > PAGE_SIZE ? (
        <div className="flex items-center justify-between gap-3 border-t border-line-soft pt-3">
          <span className="font-mono text-xs text-ink-faint tabular-nums">
            {listing.offset + 1}–{Math.min(listing.offset + listing.entries.length, listing.total)} of {listing.total}
          </span>
          <div className="flex items-center gap-2">
            <Button disabled={currentPage === 0} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <span className="font-mono text-xs text-ink-faint tabular-nums">
              Page {currentPage + 1} / {pageCount}
            </span>
            <Button disabled={currentPage + 1 >= pageCount} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </div>
        </div>
      ) : null}

      {lightboxIndex !== null ? (
        <Lightbox
          items={lightboxItems}
          index={lightboxIndex}
          onIndexChange={setLightboxIndex}
          onClose={() => setLightboxIndex(null)}
        />
      ) : null}
    </div>
  )
}

/** Appended to a `fileContentUrl` (which already has a query string). */
function cacheKey(entry: DerivativeEntry): string {
  return `&v=${entry.size}`
}

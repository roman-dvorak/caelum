import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FrameDateSummary, FrameEntry, FrameListResponse } from '@caelum/api-client'
import {
  Button,
  DownloadIcon,
  EmptyState,
  Loading,
  Message,
  PageHeader,
  Panel,
  Readout,
  RefreshIcon,
  TrashIcon,
  formatBytes,
  formatCaptureTime,
  formatSiteTime,
} from '@caelum/ui'
import { useAuth } from '../authContext.ts'
import { localApiClient } from '../services/client.ts'

type GroupMode = 'night' | 'date'
const PAGE_SIZE = 60

/**
 * The recordings manager: the capture archive as a time series rather than
 * as directories. One row per capture, with its thumbnail, sidecar and raw
 * frame collapsed together, plus the bulk deletes that actually reclaim
 * space — a night of raw frames is gigabytes, and deleting it one file at a
 * time through the file browser is not a real option.
 *
 * Two groupings, picked with the toggle below:
 * - **Night** (default) — sunrise to sunrise, local time. A session that
 *   runs past UTC midnight (the normal case anywhere east of Greenwich)
 *   stays one entry instead of splitting in two.
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
                  {option === 'night' ? 'Night' : 'Date (UTC)'}
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
          <div className="flex gap-2 overflow-x-auto pb-1">
            {summaries.map((summary) => (
              <button
                key={summary.date}
                type="button"
                onClick={() => setSelectedLabel(summary.date)}
                className={[
                  'flex shrink-0 flex-col items-start gap-0.5 border px-3 py-2 text-left transition',
                  summary.date === selectedLabel
                    ? 'border-amber bg-amber/8 text-amber'
                    : 'border-line text-ink-dim hover:border-amber-dim hover:text-ink',
                ].join(' ')}
              >
                <span className="font-mono text-sm tabular-nums">{summary.date}</span>
                <span className="text-[0.65rem] text-ink-faint tabular-nums">
                  {summary.thumbnails} frames · {summary.raws} raw · {formatBytes(summary.total_bytes)}
                </span>
              </button>
            ))}
          </div>

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
  const [listing, setListing] = useState<FrameListResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selection, setSelection] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [page, setPage] = useState(0)

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

  const totals = useMemo(() => {
    const frames = listing?.frames ?? []
    return {
      raws: frames.filter((f) => f.raw).length,
      bytes: frames.reduce((sum, f) => sum + f.total_bytes, 0),
    }
  }, [listing])

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

  return (
    <div className="flex flex-col gap-4">
      <Panel
        title={mode === 'night' ? `Night of ${label}` : label}
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
              <Button variant="danger" disabled={busy || totals.raws === 0} onClick={() => void deleteRawOnlyOnPage()}>
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
          <Readout label="Derivatives" value={listing.derivatives.length} />
          <Readout label="Page size" value={formatBytes(totals.bytes)} />
        </div>
      </Panel>

      {listing.derivatives.length > 0 ? (
        <Panel title="Derivatives">
          <div className="flex flex-col gap-3">
            {listing.derivatives.map((entry) => (
              <div key={entry.path} className="flex flex-col gap-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs text-ink-dim">{entry.name}</span>
                  <span className="font-mono text-xs text-ink-faint">{formatBytes(entry.size)}</span>
                </div>
                {entry.media === 'image' ? (
                  // Not `w-full`: a keogram is wide once a night's worth of
                  // columns has built up, but the "live" one starts as just
                  // a handful of columns — portrait, not landscape — and
                  // `w-full` would stretch that sliver to full width, which
                  // blows the height up proportionally to match. Capping
                  // height and letting width follow (object-contain) scales
                  // correctly either way, mid-night or finished.
                  <img
                    src={localApiClient.fileContentUrl(entry.path)}
                    alt={entry.name}
                    loading="lazy"
                    className="mx-auto max-h-40 max-w-full border border-line-soft bg-void object-contain"
                  />
                ) : null}
              </div>
            ))}
          </div>
        </Panel>
      ) : null}

      {listing.frames.length === 0 ? (
        <EmptyState>No captures on this page.</EmptyState>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {listing.frames.map((frame) => (
            <FrameTile
              key={frame.time}
              frame={frame}
              timezone={timezone}
              selected={selection.has(frame.time)}
              selectable={isAdmin}
              onToggle={() => toggle(frame.time)}
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
    </div>
  )
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

function FrameTile({
  frame,
  timezone,
  selected,
  selectable,
  onToggle,
}: {
  frame: FrameEntry
  timezone: string | null
  selected: boolean
  selectable: boolean
  onToggle: () => void
}) {
  // Prefer the thumbnail; fall back to a rendered raw preview for captures
  // whose thumbnail has already been rotated away by retention.
  const imageUrl = frame.thumbnail
    ? localApiClient.fileContentUrl(frame.thumbnail)
    : frame.raw
      ? localApiClient.filePreviewUrl(frame.raw, 400)
      : null

  // The site's local time is the primary reading (what a human standing at
  // the camera would see on a clock); the raw UTC stem stays available as a
  // tooltip so the two can always be cross-checked, never just one or the
  // other silently.
  const site = timezone ? formatSiteTime(frame.captured_at, timezone) : null

  return (
    <figure
      className={[
        'flex flex-col overflow-hidden border bg-panel transition',
        selected ? 'border-amber' : 'border-line',
      ].join(' ')}
    >
      <div className="relative aspect-4/3 bg-void">
        {imageUrl ? (
          <img src={imageUrl} alt={frame.time} loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <span className="flex h-full items-center justify-center text-xs text-ink-faint">
            no image
          </span>
        )}
        {selectable ? (
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            aria-label={`Select capture ${frame.time}`}
            className="absolute top-2 left-2 h-4 w-4 accent-amber"
          />
        ) : null}
        {frame.raw === null && frame.thumbnail !== null ? (
          <span className="absolute top-2 right-2 bg-void/85 px-1.5 py-0.5 font-mono text-[0.6rem] tracking-wide text-ink-faint">
            thumb only
          </span>
        ) : null}
      </div>

      <figcaption className="flex flex-col gap-1.5 border-t border-line-soft px-2 py-1.5">
        {/* Which of the three files this capture actually has on disk.
            Retention deletes raw frames long before thumbnails, so these
            diverge as a night ages. */}
        <div className="flex items-center gap-1">
          <AssetChip label="IMG" path={frame.thumbnail} title="thumbnail" />
          <AssetChip label="RAW" path={frame.raw} title="raw FITS frame" />
          <AssetChip label="JSON" path={frame.metadata} title="metadata sidecar" />
          <span className="ml-auto font-mono text-[0.65rem] text-ink-faint tabular-nums">
            {formatBytes(frame.total_bytes)}
          </span>
        </div>

        <div className="flex items-center justify-between gap-2" title={formatCaptureTime(frame.time)}>
          <span className="font-mono text-xs text-ink-dim tabular-nums">
            {site ? `${site.clock} ${site.zone}` : formatCaptureTime(frame.time)}
          </span>
          {frame.raw ? (
            <a
              href={localApiClient.fileContentUrl(frame.raw, true)}
              title="Download raw FITS"
              className="text-ink-faint hover:text-amber"
            >
              <DownloadIcon size={14} />
            </a>
          ) : null}
        </div>
      </figcaption>
    </figure>
  )
}

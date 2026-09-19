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
} from '@caelum/ui'
import { useAuth } from '../authContext.ts'
import { localApiClient } from '../services/client.ts'

/**
 * The recordings manager: the capture archive as a time series rather than
 * as directories. One row per capture, with its thumbnail, sidecar and raw
 * frame collapsed together, plus the bulk deletes that actually reclaim
 * space — a night of raw frames is gigabytes, and deleting it one file at a
 * time through the file browser is not a real option.
 */
export function Frames() {
  const { isAdmin } = useAuth()
  const [dates, setDates] = useState<FrameDateSummary[] | null>(null)
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Re-runs the date fetch from handlers without those handlers touching
  // state themselves — see the same idiom in Files.tsx and hooks/useStatus.
  const [reloadToken, setReloadToken] = useState(0)
  const reloadDates = useCallback(async () => setReloadToken((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false

    async function run() {
      try {
        const result = await localApiClient.listFrameDates()
        if (cancelled) return
        setDates(result)
        setSelectedDate((current) => current ?? result[0]?.date ?? null)
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [reloadToken])

  async function deleteDate(date: string) {
    if (!window.confirm(`Delete every file captured on ${date}? This cannot be undone.`)) return
    try {
      await localApiClient.deleteFrames({ date })
      setSelectedDate(null)
      await reloadDates()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <>
      <PageHeader
        title="Recordings"
        description="Captured frames by night, with the raw files and derivatives that belong to each."
        actions={
          <Button icon={<RefreshIcon size={14} />} onClick={() => void reloadDates()}>
            Refresh
          </Button>
        }
      />

      {error ? <Message kind="error">{error}</Message> : null}

      {dates === null ? (
        <Loading />
      ) : dates.length === 0 ? (
        <EmptyState>Nothing recorded yet.</EmptyState>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex gap-2 overflow-x-auto pb-1">
            {dates.map((summary) => (
              <button
                key={summary.date}
                type="button"
                onClick={() => setSelectedDate(summary.date)}
                className={[
                  'flex shrink-0 flex-col items-start gap-0.5 border px-3 py-2 text-left transition',
                  summary.date === selectedDate
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

          {selectedDate ? (
            <DateDetail
              key={selectedDate}
              date={selectedDate}
              isAdmin={isAdmin}
              onDeleteDate={() => void deleteDate(selectedDate)}
              onChanged={reloadDates}
            />
          ) : null}
        </div>
      )}
    </>
  )
}

function DateDetail({
  date,
  isAdmin,
  onDeleteDate,
  onChanged,
}: {
  date: string
  isAdmin: boolean
  onDeleteDate: () => void
  onChanged: () => Promise<void>
}) {
  const [listing, setListing] = useState<FrameListResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selection, setSelection] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  const [reloadToken, setReloadToken] = useState(0)
  const reload = useCallback(async () => setReloadToken((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false

    async function run() {
      try {
        const next = await localApiClient.listFrames(date)
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
  }, [date, reloadToken])

  const totals = useMemo(() => {
    const frames = listing?.frames ?? []
    return {
      count: frames.length,
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
    if (!window.confirm(`Delete ${selection.size} capture(s) from ${date}?`)) return
    setBusy(true)
    try {
      await localApiClient.deleteFrames({ date, times: [...selection] })
      await reload()
      await onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  /** Delete only the raw FITS files, keeping thumbnails and metadata — the
   * usual way to reclaim most of a night's space without losing the record
   * that the night happened. */
  async function deleteRawOnly() {
    if (!window.confirm(`Delete all raw frames from ${date}, keeping thumbnails?`)) return
    setBusy(true)
    try {
      await localApiClient.deleteFrames({ date, kinds: ['raw'] })
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

  return (
    <div className="flex flex-col gap-4">
      <Panel
        title={date}
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
              <Button variant="danger" disabled={busy || totals.raws === 0} onClick={() => void deleteRawOnly()}>
                Delete raw only
              </Button>
              <Button variant="danger" icon={<TrashIcon size={14} />} disabled={busy} onClick={onDeleteDate}>
                Delete date
              </Button>
            </>
          ) : null
        }
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Readout label="Captures" value={totals.count} />
          <Readout label="With raw" value={totals.raws} />
          <Readout label="Derivatives" value={listing.derivatives.length} />
          <Readout label="Total size" value={formatBytes(totals.bytes)} />
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
                  <img
                    src={localApiClient.fileContentUrl(entry.path)}
                    alt={entry.name}
                    loading="lazy"
                    className="w-full border border-line-soft bg-void"
                  />
                ) : null}
              </div>
            ))}
          </div>
        </Panel>
      ) : null}

      {listing.frames.length === 0 ? (
        <EmptyState>No captures stored for this date.</EmptyState>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {listing.frames.map((frame) => (
            <FrameTile
              key={frame.time}
              frame={frame}
              selected={selection.has(frame.time)}
              selectable={isAdmin}
              onToggle={() => toggle(frame.time)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function FrameTile({
  frame,
  selected,
  selectable,
  onToggle,
}: {
  frame: FrameEntry
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
        {frame.raw ? (
          <span className="absolute top-2 right-2 bg-void/85 px-1.5 py-0.5 font-mono text-[0.6rem] tracking-wide text-cyan">
            RAW
          </span>
        ) : null}
      </div>
      <figcaption className="flex items-center justify-between gap-2 border-t border-line-soft px-2 py-1.5">
        <span className="font-mono text-xs text-ink-dim tabular-nums">
          {formatCaptureTime(frame.time)}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="font-mono text-[0.65rem] text-ink-faint">
            {formatBytes(frame.total_bytes)}
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
        </span>
      </figcaption>
    </figure>
  )
}

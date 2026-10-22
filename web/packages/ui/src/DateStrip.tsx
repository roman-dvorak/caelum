import type { CameraManifestDateEntry } from '@caelum/api-client'

export interface DateStripProps {
  dates: CameraManifestDateEntry[]
  selectedDate: string | null
  onSelect: (date: string) => void
  className?: string
}

/** Horizontal date scrubber for a camera's history (newest first). */
export function DateStrip({ dates, selectedDate, onSelect, className }: DateStripProps) {
  const sorted = [...dates].sort((a, b) => b.date.localeCompare(a.date))

  if (sorted.length === 0) {
    return <p className="text-sm text-ink-muted">No captured dates yet.</p>
  }

  return (
    <div className={['flex gap-2 overflow-x-auto pb-2', className ?? ''].join(' ')}>
      {sorted.map((entry) => {
        const isSelected = entry.date === selectedDate
        return (
          <button
            key={entry.date}
            type="button"
            onClick={() => onSelect(entry.date)}
            className={[
              'flex shrink-0 flex-col items-center gap-1 border px-3 py-2 text-sm transition rounded-md',
              isSelected
                ? 'border-sky bg-sky-surface text-ink'
                : 'border-border bg-panel text-ink-muted hover:border-sky',
            ].join(' ')}
          >
            <span className="font-mono font-medium">{formatDate(entry.date)}</span>
            <span className="text-[11px] text-ink-muted">
              {entry.thumbnail_count} frame{entry.thumbnail_count === 1 ? '' : 's'}
              {entry.has_raw ? ` · ${entry.raw_count} raw` : ''}
            </span>
          </button>
        )
      })}
    </div>
  )
}

function formatDate(date: string): string {
  // Dates are "YYYY-MM-DD" — render them a little friendlier without
  // pulling in a date library for one string transform.
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date)
  if (!match) return date
  const [, year, month, day] = match
  return `${day}.${month}.${year}`
}

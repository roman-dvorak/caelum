import { useState } from 'react'

export interface CalendarEntry {
  /** "YYYY-MM-DD" — a UTC calendar date or an observation-night local date,
   * whichever the caller is grouping by. Purely a label; this component
   * does no timezone conversion of its own. */
  date: string
  /** Shown as a small dot + the tooltip's headline count — frame count is
   * the natural choice, but callers can pass whatever they want summarized. */
  count: number
}

export interface CalendarProps {
  entries: CalendarEntry[]
  selected: string | null
  onSelect: (date: string) => void
  className?: string
}

const WEEKDAY_LABELS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

function daysInMonth(year: number, month: number): number {
  // month is 1-12; day 0 of the *next* month is the last day of this one.
  return new Date(Date.UTC(year, month, 0)).getUTCDate()
}

/** Monday-first weekday index (0=Mon..6=Sun) for the 1st of `year`-`month`. */
function firstWeekdayIndex(year: number, month: number): number {
  const jsDay = new Date(Date.UTC(year, month - 1, 1)).getUTCDay() // 0=Sun..6=Sat
  return (jsDay + 6) % 7
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

/**
 * A month-grid date picker, highlighting days that actually have data.
 * Deliberately does its own plain year/month/day arithmetic via `Date.UTC`
 * rather than parsing "YYYY-MM-DD" through the local-timezone-sensitive
 * `Date` constructor — these labels are calendar dates, not instants, and
 * must never shift by a day depending on the viewer's browser timezone.
 */
export function Calendar({ entries, selected, onSelect, className }: CalendarProps) {
  const byDate = new Map(entries.map((e) => [e.date, e]))
  const mostRecent = [...entries].sort((a, b) => b.date.localeCompare(a.date))[0]?.date
  const initial = selected ?? mostRecent ?? new Date().toISOString().slice(0, 10)
  const [year, setYear] = useState(() => Number(initial.slice(0, 4)))
  const [month, setMonth] = useState(() => Number(initial.slice(5, 7))) // 1-12

  function shiftMonth(delta: number) {
    let nextMonth = month + delta
    let nextYear = year
    if (nextMonth < 1) {
      nextMonth = 12
      nextYear -= 1
    } else if (nextMonth > 12) {
      nextMonth = 1
      nextYear += 1
    }
    setMonth(nextMonth)
    setYear(nextYear)
  }

  const leading = firstWeekdayIndex(year, month)
  const total = daysInMonth(year, month)
  const cells: (number | null)[] = [...Array(leading).fill(null), ...Array.from({ length: total }, (_, i) => i + 1)]

  return (
    <div className={['inline-flex flex-col gap-2 border border-line bg-panel p-3', className ?? ''].join(' ')}>
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => shiftMonth(-1)}
          className="px-2 py-1 text-ink-faint hover:text-ink"
          aria-label="Previous month"
        >
          ‹
        </button>
        <span className="font-mono text-xs font-semibold tracking-wide text-ink-dim uppercase">
          {MONTH_NAMES[month - 1]} {year}
        </span>
        <button
          type="button"
          onClick={() => shiftMonth(1)}
          className="px-2 py-1 text-ink-faint hover:text-ink"
          aria-label="Next month"
        >
          ›
        </button>
      </div>

      <div className="grid grid-cols-7 gap-1">
        {WEEKDAY_LABELS.map((w) => (
          <span key={w} className="text-center font-mono text-[10px] text-ink-faint">
            {w}
          </span>
        ))}
        {cells.map((day, i) => {
          if (day === null) return <span key={`pad-${i}`} />
          const dateStr = `${year}-${pad2(month)}-${pad2(day)}`
          const entry = byDate.get(dateStr)
          const isSelected = dateStr === selected
          return (
            <button
              key={dateStr}
              type="button"
              disabled={!entry}
              onClick={() => onSelect(dateStr)}
              title={entry ? `${dateStr} — ${entry.count} frame${entry.count === 1 ? '' : 's'}` : dateStr}
              className={[
                'flex flex-col items-center gap-0.5 py-1 font-mono text-xs transition',
                !entry ? 'cursor-default text-ink-faint/40' : 'cursor-pointer text-ink-dim hover:text-ink',
                isSelected ? 'bg-amber text-void font-semibold' : entry ? 'hover:bg-amber/10' : '',
              ].join(' ')}
            >
              <span>{day}</span>
              {entry ? (
                <span
                  className={['h-1 w-1 rounded-full', isSelected ? 'bg-void' : 'bg-amber'].join(' ')}
                />
              ) : (
                <span className="h-1 w-1" />
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}

const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]

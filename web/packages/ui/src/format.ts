/** Formatting shared by every view that shows a file size or a timestamp. */

const UNITS = ['B', 'kB', 'MB', 'GB', 'TB'] as const

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), UNITS.length - 1)
  const value = bytes / 1024 ** exponent
  // Bytes and kilobytes are never interesting to a decimal place; larger
  // units are, because that is where the retention decisions get made.
  return `${value.toFixed(exponent <= 1 ? 0 : 1)} ${UNITS[exponent]}`
}

/** `YYYYMMDD-HHMMSS` (the capture-file naming convention, always UTC) →
 * `HH:MM:SS UTC` — the raw, unconverted reading. Prefer `formatSiteTime`
 * for anything shown as *the* time of a capture; this is for contexts that
 * want the literal on-disk/UTC value made explicit (e.g. a tooltip next to
 * the converted local time, so the two can be compared directly). */
export function formatCaptureTime(stem: string): string {
  const match = /(\d{2})(\d{2})(\d{2})$/.exec(stem)
  if (!match) return stem
  const [, h, m, s] = match
  return `${h}:${m}:${s} UTC`
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

/**
 * Converts a UTC ISO timestamp to the site's configured local time
 * (`location.timezone`, from `GET /api/status`), with the zone abbreviation
 * split out so a caller can show it as a visible label rather than leaving
 * "is this UTC or local?" a guess — every timestamp the backend returns is
 * UTC, and this is the one place that turns it into what a human at the
 * camera's own site would read off a clock.
 */
export function formatSiteTime(iso: string, timezone: string): { clock: string; zone: string } {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return { clock: iso, zone: '' }

  const parts = new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: timezone,
    timeZoneName: 'short',
  }).formatToParts(date)

  const clock = parts
    .filter((p) => p.type === 'hour' || p.type === 'minute' || p.type === 'second')
    .map((p) => p.value)
    .join(':')
  const zone = parts.find((p) => p.type === 'timeZoneName')?.value ?? timezone
  return { clock, zone }
}

/** Same as `formatSiteTime`, but also including the local calendar date —
 * for a night that spans local midnight, the clock alone is ambiguous. */
export function formatSiteDateTime(iso: string, timezone: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: timezone,
    timeZoneName: 'short',
  }).format(date)
}

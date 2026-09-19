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

/** `HHMMSS` (the capture-file naming convention) → `HH:MM:SS`. */
export function formatCaptureTime(time: string): string {
  const match = /^(\d{2})(\d{2})(\d{2})/.exec(time)
  if (!match) return time
  const [, h, m, s] = match
  return `${h}:${m}:${s}`
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

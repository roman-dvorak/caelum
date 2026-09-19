import type { SkyPeriod } from '@caelum/api-client'

export const PERIOD_LABELS: Record<string, string> = {
  day: 'Day',
  civil_twilight: 'Civil twilight',
  nautical_twilight: 'Nautical twilight',
  astronomical_twilight: 'Astronomical twilight',
  night: 'Night',
}

/** A warm-to-cool gradient across the day/night cycle — amber at midday,
 * shading through to cyan at full night — rather than arbitrary category
 * colors, so the badge itself hints at where in the cycle things are. */
export const PERIOD_COLORS: Record<string, string> = {
  day: 'bg-amber/15 text-amber-bright ring-amber/50',
  civil_twilight: 'bg-amber-dim/25 text-amber ring-amber-dim/60',
  nautical_twilight: 'bg-panel-raised text-ink-dim ring-line',
  astronomical_twilight: 'bg-cyan-dim/25 text-cyan ring-cyan-dim/60',
  night: 'bg-cyan-dim/15 text-cyan ring-cyan-dim/50',
}

export function periodLabel(period: SkyPeriod | string): string {
  return PERIOD_LABELS[period] ?? period
}

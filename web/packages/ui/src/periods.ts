import type { SkyPeriod } from '@caelum/api-client'

export const PERIOD_LABELS: Record<string, string> = {
  day: 'Day',
  civil_twilight: 'Civil twilight',
  nautical_twilight: 'Nautical twilight',
  astronomical_twilight: 'Astronomical twilight',
  night: 'Night',
}

/** The sky period is what the design system's amber is for — "this is
 * happening now, from the sky" — so the badge is amber in every period; the
 * night end shades towards `sky` only through its surface, keeping amber's
 * meaning intact. */
export const PERIOD_COLORS: Record<string, string> = {
  day: 'bg-amber-surface text-amber-ink ring-amber/50',
  civil_twilight: 'bg-amber-surface text-amber-ink ring-amber/50',
  nautical_twilight: 'bg-amber-surface text-amber-ink ring-amber/50',
  astronomical_twilight: 'bg-sky-surface text-amber-ink ring-amber/50',
  night: 'bg-sky-surface text-amber-ink ring-amber/50',
}

export function periodLabel(period: SkyPeriod | string): string {
  return PERIOD_LABELS[period] ?? period
}

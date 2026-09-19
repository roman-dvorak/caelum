import type { SkyPeriod } from '@caelum/api-client'

export const PERIOD_LABELS: Record<string, string> = {
  day: 'Day',
  civil_twilight: 'Civil twilight',
  nautical_twilight: 'Nautical twilight',
  astronomical_twilight: 'Astronomical twilight',
  night: 'Night',
}

export const PERIOD_COLORS: Record<string, string> = {
  day: 'bg-sky-500/20 text-sky-200 ring-sky-400/40',
  civil_twilight: 'bg-amber-500/20 text-amber-200 ring-amber-400/40',
  nautical_twilight: 'bg-indigo-500/20 text-indigo-200 ring-indigo-400/40',
  astronomical_twilight: 'bg-violet-500/20 text-violet-200 ring-violet-400/40',
  night: 'bg-slate-800/60 text-slate-200 ring-slate-500/40',
}

export function periodLabel(period: SkyPeriod | string): string {
  return PERIOD_LABELS[period] ?? period
}

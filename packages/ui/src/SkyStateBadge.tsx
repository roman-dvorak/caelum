import type { SkyState } from '@caelum/api-client'
import { PERIOD_COLORS, periodLabel } from './periods.js'

export interface SkyStateBadgeProps {
  skyState: Pick<SkyState, 'sun_altitude_deg' | 'moon_illumination' | 'period'>
  /** Renders a smaller, denser variant for use inside the image overlay. */
  compact?: boolean
  className?: string
}

export function SkyStateBadge({ skyState, compact = false, className }: SkyStateBadgeProps) {
  const colors = PERIOD_COLORS[skyState.period] ?? 'bg-slate-700/60 text-slate-200 ring-slate-500/40'
  return (
    <div
      className={[
        'inline-flex items-center gap-2 rounded-full ring-1 backdrop-blur-sm',
        colors,
        compact ? 'px-2 py-0.5 text-xs' : 'px-3 py-1.5 text-sm',
        className ?? '',
      ].join(' ')}
    >
      <span className="font-medium">{periodLabel(skyState.period)}</span>
      <span className="opacity-80">☉ {skyState.sun_altitude_deg.toFixed(1)}°</span>
      <span className="opacity-80">☾ {Math.round(skyState.moon_illumination * 100)}%</span>
    </div>
  )
}

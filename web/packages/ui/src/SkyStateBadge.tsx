import type { SkyState } from '@caelum/api-client'
import { PERIOD_COLORS, periodLabel } from './periods.js'

export interface SkyStateBadgeProps {
  skyState: Pick<SkyState, 'sun_altitude_deg' | 'moon_illumination' | 'period'>
  /** Renders a smaller, denser variant for use inside the image overlay. */
  compact?: boolean
  className?: string
}

export function SkyStateBadge({ skyState, compact = false, className }: SkyStateBadgeProps) {
  const colors = PERIOD_COLORS[skyState.period] ?? 'bg-panel-raised text-ink-dim ring-line'
  return (
    <div
      className={[
        'tabular-nums inline-flex items-center gap-2.5 font-mono ring-1 backdrop-blur-sm',
        colors,
        compact ? 'px-2 py-1 text-[11px]' : 'px-3 py-1.5 text-xs',
        className ?? '',
      ].join(' ')}
    >
      <span className="font-sans font-semibold tracking-wide uppercase">{periodLabel(skyState.period)}</span>
      <span className="opacity-70">☉{skyState.sun_altitude_deg.toFixed(1)}°</span>
      <span className="opacity-70">☾{Math.round(skyState.moon_illumination * 100)}%</span>
    </div>
  )
}

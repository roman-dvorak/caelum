import type { SkyState } from '@caelum/api-client'
import { PERIOD_COLORS, periodLabel } from './periods.js'
import { MoonIcon, SunIcon } from './icons.js'

export interface SkyStateBadgeProps {
  skyState: Pick<SkyState, 'sun_altitude_deg' | 'moon_illumination' | 'period'>
  /** Renders a smaller, denser variant for use inside the image overlay. */
  compact?: boolean
  className?: string
}

/** The active sky period — the design system's one amber-glow badge. */
export function SkyStateBadge({ skyState, compact = false, className }: SkyStateBadgeProps) {
  const colors = PERIOD_COLORS[skyState.period] ?? 'bg-panel-raised text-ink-muted ring-border'
  return (
    <div
      className={[
        'tabular-nums inline-flex items-center gap-2.5 rounded-xs font-mono ring-1 shadow-glow-amber backdrop-blur-sm',
        colors,
        compact ? 'px-2 py-1 text-code-sm' : 'px-3 py-1.5 text-code-sm',
        className ?? '',
      ].join(' ')}
    >
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber" />
      <span className="font-sans text-label-sm tracking-[0.08em] uppercase">{periodLabel(skyState.period)}</span>
      <span className="inline-flex items-center gap-1 text-ink-muted">
        <SunIcon size={13} />
        {skyState.sun_altitude_deg.toFixed(1)}°
      </span>
      <span className="inline-flex items-center gap-1 text-ink-muted">
        <MoonIcon size={13} />
        {Math.round(skyState.moon_illumination * 100)}%
      </span>
    </div>
  )
}

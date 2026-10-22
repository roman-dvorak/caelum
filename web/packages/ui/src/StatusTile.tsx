import type { ReactNode } from 'react'

export interface StatusTileProps {
  label: string
  value: ReactNode
  unit?: string
  hint?: string
  className?: string
}

/** The design system's MetricTile: one value with its label and unit. The
 * label is a tag (`label-sm`, uppercase); the value a display-size number. */
export function StatusTile({ label, value, unit, hint, className }: StatusTileProps) {
  return (
    <div className={['flex min-w-0 flex-col gap-1.5 rounded-lg border border-border bg-panel-raised px-4 py-3', className ?? ''].join(' ')}>
      <span className="text-label-sm tracking-[0.08em] text-ink-muted uppercase">{label}</span>
      <span className="tabular-nums flex min-w-0 items-baseline gap-1.5 font-display text-display-md text-ink [overflow-wrap:anywhere]">
        {value}
        {unit ? <span className="font-sans text-sm font-normal text-ink-muted">{unit}</span> : null}
      </span>
      {hint ? <span className="text-xs text-ink-muted">{hint}</span> : null}
    </div>
  )
}

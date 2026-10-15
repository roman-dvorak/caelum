import type { ReactNode } from 'react'

export interface StatusTileProps {
  label: string
  value: ReactNode
  unit?: string
  hint?: string
  className?: string
}

export function StatusTile({ label, value, unit, hint, className }: StatusTileProps) {
  return (
    <div
      className={['flex flex-col gap-1.5 border-l-2 border-line bg-panel px-4 py-3', className ?? ''].join(' ')}
    >
      <span className="text-[10px] font-semibold tracking-[0.15em] text-ink-faint uppercase">{label}</span>
      <span className="tabular-nums flex items-baseline gap-1 font-mono text-xl font-medium text-ink">
        {value}
        {unit ? <span className="font-sans text-xs font-normal text-ink-dim">{unit}</span> : null}
      </span>
      {hint ? <span className="text-xs text-ink-faint">{hint}</span> : null}
    </div>
  )
}

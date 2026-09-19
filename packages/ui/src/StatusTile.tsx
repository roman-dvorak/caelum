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
      className={[
        'flex flex-col gap-1 rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-3',
        className ?? '',
      ].join(' ')}
    >
      <span className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</span>
      <span className="flex items-baseline gap-1 text-xl font-semibold text-slate-100">
        {value}
        {unit ? <span className="text-sm font-normal text-slate-400">{unit}</span> : null}
      </span>
      {hint ? <span className="text-xs text-slate-500">{hint}</span> : null}
    </div>
  )
}

/**
 * The handful of surfaces and controls every page repeats. Extracted here
 * so a button in the file browser and a button in the settings page are
 * literally the same element, rather than two Tailwind strings that drifted
 * apart.
 */

import type { ButtonHTMLAttributes, ReactNode } from 'react'

export function Panel({
  title,
  actions,
  children,
  className = '',
  bodyClassName = 'p-4',
}: {
  title?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={`border border-line bg-panel shadow-[var(--shadow-panel)] ${className}`}>
      {title || actions ? (
        <header className="flex items-center justify-between gap-3 border-b border-line-soft px-4 py-2.5">
          <h2 className="text-xs font-semibold tracking-[0.15em] text-ink-dim uppercase">{title}</h2>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-amber text-void hover:bg-amber-bright border border-transparent font-semibold',
  secondary: 'border border-line text-ink-dim hover:border-amber-dim hover:text-ink',
  danger: 'border border-danger/50 text-danger hover:bg-danger/10',
  ghost: 'border border-transparent text-ink-faint hover:text-ink',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  icon?: ReactNode
}

export function Button({
  variant = 'secondary',
  icon,
  children,
  className = '',
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={[
        'inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs tracking-wide uppercase transition',
        'disabled:cursor-not-allowed disabled:opacity-40',
        VARIANTS[variant],
        className,
      ].join(' ')}
      {...props}
    >
      {icon}
      {children}
    </button>
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium tracking-wide text-ink-dim uppercase">{label}</span>
      {children}
      {hint ? <span className="text-xs text-ink-faint">{hint}</span> : null}
    </label>
  )
}

export const inputClass =
  'w-full border border-line bg-void px-3 py-1.5 font-mono text-sm text-ink transition focus:border-amber focus:outline-none'

export function Message({ kind, children }: { kind: 'error' | 'info' | 'success'; children: ReactNode }) {
  const styles = {
    error: 'border-danger/40 bg-danger/10 text-danger',
    info: 'border-line bg-panel-raised text-ink-dim',
    success: 'border-success/40 bg-success/10 text-success',
  }[kind]
  return <p className={`border px-3 py-2 text-sm ${styles}`}>{children}</p>
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="border border-dashed border-line px-4 py-10 text-center text-sm text-ink-faint">
      {children}
    </div>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <p className="py-4 text-sm text-ink-faint">{label}</p>
}

/** Small key/value readout — the unit of the dashboard and file details. */
export function Readout({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[0.65rem] tracking-[0.15em] text-ink-faint uppercase">{label}</span>
      <span className="font-mono text-sm text-ink tabular-nums">{value}</span>
    </div>
  )
}

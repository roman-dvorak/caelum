/**
 * The handful of surfaces and controls every page repeats, styled by the
 * Caelum design system. Extracted here so a button in the file browser and
 * a button in the settings page are literally the same element, rather than
 * two Tailwind strings that drifted apart.
 */

import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { ErrorIcon, InfoIcon, SpinnerIcon, SuccessIcon } from './icons.js'
import { buttonClass } from './buttonClass.js'
import type { ButtonVariant } from './buttonClass.js'

/** A card: `radius-lg`, one step lighter than what it sits on. */
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
    <section className={`overflow-hidden rounded-lg border border-border bg-panel shadow-sm ${className}`}>
      {title || actions ? (
        <header className="flex items-center justify-between gap-3 border-b border-border-subtle px-4 py-3">
          <h2 className="font-display text-display-sm text-ink">{title}</h2>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  icon?: ReactNode
}

export function Button({ variant = 'secondary', icon, children, className = '', type = 'button', ...props }: ButtonProps) {
  return (
    <button type={type} className={buttonClass(variant, className)} {...props}>
      {icon}
      {children}
    </button>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-label-md text-ink-muted">{label}</span>
      {children}
      {hint ? <span className="text-xs text-ink-muted">{hint}</span> : null}
    </label>
  )
}

/** Values typed into the camera are data: `mono`. Focus is `sky`. */
export const inputClass =
  'w-full rounded-md border border-border bg-surface-0 px-3 py-1.5 font-mono text-code-md text-ink transition focus:border-sky focus:shadow-glow-sky focus:outline-none disabled:text-ink-dim'

type MessageKind = 'error' | 'info' | 'success' | 'warning'

const MESSAGE_STYLES: Record<MessageKind, { box: string; icon: ReactNode }> = {
  error: { box: 'border-error/40 bg-error-surface', icon: <ErrorIcon size={18} className="text-error" /> },
  warning: { box: 'border-amber/40 bg-amber-surface', icon: <ErrorIcon size={18} className="text-amber" /> },
  info: { box: 'border-sky/40 bg-sky-surface', icon: <InfoIcon size={18} className="text-sky" /> },
  success: { box: 'border-success/40 bg-success-surface', icon: <SuccessIcon size={18} className="text-success" /> },
}

/** A callout: a status colour only as its `*-surface` fill, border and
 * icon; the text stays `ink` so it reads in both themes. */
export function Message({ kind, icon, children }: { kind: MessageKind; icon?: ReactNode; children: ReactNode }) {
  const style = MESSAGE_STYLES[kind]
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={`flex items-start gap-2.5 rounded-md border px-3 py-2.5 text-sm text-ink ${style.box}`}>
      <span className="mt-0.5 shrink-0">{icon ?? style.icon}</span>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

type BadgeTone = 'live' | 'success' | 'warning' | 'error' | 'info' | 'neutral'

const BADGE_TONES: Record<BadgeTone, string> = {
  live: 'border-amber/50 bg-amber-surface text-amber-ink',
  success: 'border-success/50 bg-success-surface text-ink',
  warning: 'border-amber/50 bg-amber-surface text-ink',
  error: 'border-error/50 bg-error-surface text-error',
  info: 'border-sky/50 bg-sky-surface text-ink',
  neutral: 'border-border bg-panel-raised text-ink-muted',
}

const BADGE_DOTS: Partial<Record<BadgeTone, string>> = {
  live: 'bg-amber shadow-glow-amber',
  success: 'bg-success',
  warning: 'bg-amber',
  error: 'bg-error',
  info: 'bg-sky',
}

/** A status label: `label-sm`, uppercase, `radius-xs`. `live` is amber —
 * use it only for what the camera is doing right now. */
export function StatusBadge({ tone = 'neutral', children, className = '' }: { tone?: BadgeTone; children: ReactNode; className?: string }) {
  const dot = BADGE_DOTS[tone]
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-xs border px-2 py-1 text-label-sm tracking-[0.08em] whitespace-nowrap uppercase ${BADGE_TONES[tone]} ${className}`}
    >
      {dot ? <span className={`h-1.5 w-1.5 rounded-full ${dot}`} /> : null}
      {children}
    </span>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-border px-4 py-10 text-center text-sm text-ink-muted">
      {children}
    </div>
  )
}

/** Something is in progress and will finish on its own. Turns only where
 * the viewer allows motion; still, it reads as the progress glyph. */
export function Spinner({ size = 18, className = 'text-sky' }: { size?: number; className?: string }) {
  return <SpinnerIcon size={size} className={`motion-safe:animate-spin ${className}`} />
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <p className="py-4 text-sm text-ink-muted">{label}</p>
}

/** Small key/value readout — the unit of the dashboard and file details.
 * The value is a measurement, so `mono`. */
export function Readout({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-label-sm tracking-[0.08em] text-ink-muted uppercase">{label}</span>
      <span className="font-mono text-code-md text-ink tabular-nums">{value}</span>
    </div>
  )
}

/** A section title inside a page: `display-sm`. */
export function SectionHeading({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h2 className="font-display text-display-sm text-ink">{children}</h2>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  )
}

/** Grid of `StatusTile`s (the design system's MetricTile). */
export function MetricGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{children}</div>
}

/** The design system's LiveFrame: the camera image in a `radius-lg` frame
 * whose border glows amber while the camera is capturing — the one place
 * `shadow-glow-amber` says "this is live". */
export function LiveFrame({ live = false, children, className = '' }: { live?: boolean; children: ReactNode; className?: string }) {
  return (
    <section
      className={[
        'relative overflow-hidden rounded-lg border bg-surface-0 transition-shadow',
        live ? 'border-amber/60 shadow-glow-amber' : 'border-border',
        className,
      ].join(' ')}
    >
      {children}
    </section>
  )
}

/** One choice out of a few, side by side; the chosen one in the
 * navigation colour (`sky`). */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  className = '',
}: {
  options: readonly { value: T; label: ReactNode }[]
  value: T
  onChange: (value: T) => void
  className?: string
}) {
  return (
    <div role="radiogroup" className={`inline-flex gap-0.5 rounded-md border border-border bg-surface-0 p-0.5 ${className}`}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          onClick={() => onChange(option.value)}
          className={[
            'rounded-sm px-3 py-1 text-sm font-medium transition',
            option.value === value ? 'bg-sky-surface text-ink shadow-sm ring-1 ring-sky/40' : 'text-ink-muted hover:text-ink',
          ].join(' ')}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

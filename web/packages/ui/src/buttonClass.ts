/** Button styling, kept out of primitives.tsx so that file exports only
 * components (react-refresh requires the split). */

export type ButtonVariant = 'primary' | 'secondary' | 'error' | 'ghost'

/** `primary` is amber — the dashboard's one call to action per view, not
 * every button; everything else is `secondary`. */
const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'border border-transparent bg-amber text-on-amber hover:bg-amber-light active:bg-amber-dim',
  secondary: 'border border-border text-ink hover:border-sky hover:bg-surface-400/40',
  error: 'border border-error/60 text-error hover:bg-error-surface',
  ghost: 'border border-transparent text-ink-muted hover:bg-surface-400/40 hover:text-ink',
}

/** Shared by `Button` and the few link-styled-as-button elements. */
export function buttonClass(variant: ButtonVariant = 'secondary', className = ''): string {
  return [
    'inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-semibold transition',
    'disabled:cursor-not-allowed disabled:opacity-40',
    VARIANTS[variant],
    className,
  ].join(' ')
}


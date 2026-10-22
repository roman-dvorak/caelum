/** Nav shapes and styling, kept out of AppShell.tsx so that file exports
 * only components (react-refresh requires the split). */

import type { ComponentType } from 'react'
import type { IconProps } from './icons.js'

export interface NavItem {
  to: string
  label: string
  icon: ComponentType<IconProps>
  /** Match the route exactly rather than as a prefix (for the "/" entry). */
  end?: boolean
}

export interface NavSection {
  title?: string
  items: NavItem[]
}

const NAV_BASE = 'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition select-none'

/** Shared class function for nav links, so both apps highlight identically.
 * The current page is `sky` — the design system's navigation colour; amber
 * stays reserved for what the camera is doing. */
export function navItemClass(isActive: boolean): string {
  return [
    NAV_BASE,
    isActive ? 'bg-sky-surface text-ink [&>svg]:text-sky' : 'text-ink-muted hover:bg-surface-400/40 hover:text-ink',
  ].join(' ')
}

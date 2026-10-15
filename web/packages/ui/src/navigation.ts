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

const NAV_BASE = 'flex items-center gap-2.5 border-l-2 px-3 py-2 text-sm transition select-none'

/** Shared class function for nav links, so both apps highlight identically. */
export function navItemClass(isActive: boolean): string {
  return [
    NAV_BASE,
    isActive
      ? 'border-amber bg-amber/8 text-amber'
      : 'border-transparent text-ink-dim hover:border-line hover:bg-panel-raised hover:text-ink',
  ].join(' ')
}

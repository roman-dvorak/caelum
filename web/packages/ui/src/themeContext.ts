/** Theme state and the hook that reads it. Split from theme.tsx so that
 * file exports only components (react-refresh requires the split). */

import { createContext, useContext } from 'react'

export type ThemePreference = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'caelum:theme'

export interface ThemeContextValue {
  /** What the user chose, including 'system'. */
  preference: ThemePreference
  /** What is actually on screen — 'system' already resolved. */
  theme: ResolvedTheme
  setPreference: (preference: ThemePreference) => void
  /** Cycles light → dark → system, which is what the toggle button does. */
  cycle: () => void
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme() must be used inside a <ThemeProvider>')
  return context
}

export function systemTheme(): ResolvedTheme {
  if (typeof window === 'undefined') return 'dark'
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export function readStoredPreference(): ThemePreference {
  if (typeof localStorage === 'undefined') return 'system'
  const stored = localStorage.getItem(THEME_STORAGE_KEY)
  return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
}

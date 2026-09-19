import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { MoonIcon, SunIcon } from './icons.js'
import {
  THEME_STORAGE_KEY,
  ThemeContext,
  readStoredPreference,
  systemTheme,
  useTheme,
} from './themeContext.js'
import type { ResolvedTheme, ThemePreference } from './themeContext.js'

/**
 * Owns the theme for an app. Resolves 'system' in JS and writes a concrete
 * `data-theme="light" | "dark"` onto <html>, so theme.css only ever needs a
 * single attribute selector rather than reconciling an explicit choice with
 * a `prefers-color-scheme` media query.
 *
 * Pair with the inline script in each app's index.html, which applies the
 * stored preference before React mounts — without it the page paints in the
 * default theme first and visibly flips.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredPreference)
  const [resolvedSystem, setResolvedSystem] = useState<ResolvedTheme>(systemTheme)

  // Track the OS setting so a 'system' preference follows it live, rather
  // than only at page load.
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: light)')
    const onChange = () => setResolvedSystem(media.matches ? 'light' : 'dark')
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  const theme: ResolvedTheme = preference === 'system' ? resolvedSystem : preference

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next)
    localStorage.setItem(THEME_STORAGE_KEY, next)
  }, [])

  const cycle = useCallback(() => {
    setPreferenceState((current) => {
      const next: ThemePreference = current === 'light' ? 'dark' : current === 'dark' ? 'system' : 'light'
      localStorage.setItem(THEME_STORAGE_KEY, next)
      return next
    })
  }, [])

  const value = useMemo(
    () => ({ preference, theme, setPreference, cycle }),
    [preference, theme, setPreference, cycle],
  )

  return <ThemeContext value={value}>{children}</ThemeContext>
}

const LABELS: Record<ThemePreference, string> = {
  light: 'Light',
  dark: 'Dark',
  system: 'System',
}

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { preference, theme, cycle } = useTheme()

  return (
    <button
      type="button"
      onClick={cycle}
      title={`Theme: ${LABELS[preference]} — click to change`}
      aria-label={`Theme: ${LABELS[preference]}. Click to change.`}
      className={[
        'flex items-center gap-2 border border-line text-ink-dim transition',
        'hover:border-amber-dim hover:text-ink',
        compact ? 'h-8 w-8 justify-center' : 'w-full px-2.5 py-1.5 text-xs',
      ].join(' ')}
    >
      {theme === 'light' ? <SunIcon size={16} /> : <MoonIcon size={16} />}
      {compact ? null : (
        <span className="tracking-wide uppercase">
          {LABELS[preference]}
          {preference === 'system' ? <span className="text-ink-faint"> · {theme}</span> : null}
        </span>
      )}
    </button>
  )
}

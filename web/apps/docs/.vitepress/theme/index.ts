import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import './caelum.css'

/**
 * VitePress' default theme with the caelum palette applied over it.
 *
 * Deliberately not a custom theme: the docs need search, a sidebar, prev/next
 * links and a working mobile layout far more than they need bespoke layout
 * code, and the default theme is entirely driven by CSS variables — so
 * matching the app is a stylesheet, not a fork.
 */
export default DefaultTheme satisfies Theme

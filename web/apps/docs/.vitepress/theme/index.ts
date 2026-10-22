import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import { h } from 'vue'
import ConsentBanner from './ConsentBanner.vue'
import '@fontsource-variable/inter'
import '@fontsource-variable/space-grotesk'
import '@fontsource-variable/jetbrains-mono'
import './caelum.css'

/**
 * VitePress' default theme with the Caelum design system applied over it.
 *
 * Deliberately not a custom theme: the docs need search, a sidebar, prev/next
 * links and a working mobile layout far more than they need bespoke layout
 * code, and the default theme is entirely driven by CSS variables — so
 * matching the app is a stylesheet, not a fork. The one addition is the
 * analytics consent banner (analytics.ts), in a layout slot.
 */
export default {
  extends: DefaultTheme,
  Layout: () => h(DefaultTheme.Layout, null, { 'layout-bottom': () => h(ConsentBanner) }),
} satisfies Theme

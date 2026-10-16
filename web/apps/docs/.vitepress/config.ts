import { createRequire } from 'node:module'
import { dirname } from 'node:path'
import { defineConfig } from 'vitepress'

// The pages are compiled to Vue components that import `vue`, but they sit in
// the repository's docs/, outside the pnpm workspace, where Node's resolution
// never reaches web/node_modules. Point it at the very copy VitePress itself
// uses, so there is exactly one Vue instance in the bundle.
const vitepressRequire = createRequire(createRequire(import.meta.url).resolve('vitepress'))
const vueDir = dirname(vitepressRequire.resolve('vue/package.json'))

/**
 * Public documentation site.
 *
 * The pages live in the repository's top-level `docs/` (`srcDir` below), next
 * to the code they describe; only the tooling sits here in the pnpm workspace.
 * Published to GitHub Pages by .github/workflows/docs.yml, and can also be
 * rsynced as plain static files next to the remote gallery on an Apache host
 * (scripts/deploy-static.sh). Deep-linked from the local web UI — which is why the
 * route names below are a contract, not cosmetics: `config.docs.base_url`
 * in the backend plus paths like `/guide/security` and `/guide/concepts`
 * are referenced from Login.tsx and Settings.tsx.
 *
 * `DOCS_BASE` covers hosting under a subdirectory (e.g. "/caelum/docs/");
 * it must have a leading and trailing slash.
 */
const base = process.env.DOCS_BASE || '/'

export default defineConfig({
  title: 'caelum',
  description: 'Software stack for allsky and astronomical cameras',
  base,
  srcDir: '../../../docs',
  lang: 'en',
  // Extension-less URLs need `MultiViews` or a rewrite rule, and the target
  // here is a stock Apache static root that the camera merely rsyncs into —
  // no vhost config of its own. Emitting real `.html` files works on any
  // static host, at the cost of slightly longer URLs.
  cleanUrls: false,
  lastUpdated: true,
  // Apache serves these as files on disk; a broken relative link is a 404
  // for a reader, so fail the build instead of shipping one.
  ignoreDeadLinks: false,

  vite: {
    resolve: { alias: { vue: vueDir } },
  },

  head: [
    ['meta', { name: 'theme-color', content: '#e8a13a' }],
    ['link', { rel: 'icon', href: `${base}favicon.svg` }],
  ],

  themeConfig: {
    nav: [
      { text: 'Guide', link: '/guide/', activeMatch: '/guide/' },
      { text: 'Getting started', link: '/guide/getting-started' },
      { text: 'Reference', link: '/capture-programs' },
    ],

    socialLinks: [{ icon: 'github', link: 'https://github.com/roman-dvorak/caelum' }],

    editLink: {
      pattern: 'https://github.com/roman-dvorak/caelum/edit/master/docs/:path',
    },

    sidebar: [
      {
        text: 'Start here',
        items: [
          { text: 'Introduction', link: '/guide/' },
          { text: 'Getting started', link: '/guide/getting-started' },
          { text: 'Concepts', link: '/guide/concepts' },
        ],
      },
      {
        text: 'Running a camera',
        items: [
          { text: 'Cameras', link: '/guide/cameras' },
          { text: 'Exposure control', link: '/guide/exposure' },
          { text: 'Storage & retention', link: '/guide/storage' },
          { text: 'Upload & archive', link: '/guide/upload' },
        ],
      },
      {
        text: 'Operating',
        items: [
          { text: 'Web interface', link: '/guide/web-ui' },
          { text: 'Access & security', link: '/guide/security' },
          { text: 'Deployment', link: '/guide/deployment' },
          { text: 'Updates', link: '/guide/updates' },
          { text: 'Plugins', link: '/guide/plugins' },
        ],
      },
      {
        text: 'Reference',
        items: [
          { text: 'Capture programs', link: '/capture-programs' },
          { text: 'Capture sets in DNG', link: '/dng-capture-sets' },
        ],
      },
    ],

    // Bundled at build time — no external service, so the docs stay fully
    // self-hosted and work on a LAN-only mirror.
    search: { provider: 'local' },

    outline: { level: [2, 3] },

    footer: {
      message: 'caelum — part of the astrometers instrumentation stack',
      copyright: 'astrometers.eu',
    },
  },
})

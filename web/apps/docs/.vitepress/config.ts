import { defineConfig } from 'vitepress'

/**
 * Public documentation site.
 *
 * Deployed as plain static files next to the remote gallery on the same
 * Apache host, and deep-linked from the local web UI — which is why the
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

  head: [
    ['meta', { name: 'theme-color', content: '#e8a13a' }],
    ['link', { rel: 'icon', href: `${base}favicon.svg` }],
  ],

  themeConfig: {
    nav: [
      { text: 'Guide', link: '/guide/', activeMatch: '/guide/' },
      { text: 'Getting started', link: '/guide/getting-started' },
    ],

    sidebar: {
      '/guide/': [
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
            { text: 'Plugins', link: '/guide/plugins' },
          ],
        },
      ],
    },

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

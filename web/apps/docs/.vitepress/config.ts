import { createRequire } from 'node:module'
import { dirname } from 'node:path'
import { defineConfig, type HeadConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'
import { DEVELOPER_NAME, DEVELOPER_URL, DOCS_URL } from '../../../packages/ui/src/brand.ts'

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
 * route names below are a contract, not cosmetics: `DOCS_URL` in
 * packages/ui/src/brand.ts plus paths like `/guide/security` and
 * `/guide/concepts` are referenced from Login.tsx and Settings.tsx.
 *
 * `DOCS_BASE` covers hosting under a subdirectory (e.g. "/caelum/docs/");
 * it must have a leading and trailing slash.
 */
const base = process.env.DOCS_BASE || '/'

/** The public site — what search engines index. Sitemap, canonical and Open
 * Graph URLs point here even from a mirror built with another DOCS_BASE, so a
 * copy never competes with the original. */
const siteUrl = DOCS_URL.replace(/\/$/, '')

const ogImage = `${siteUrl}/og-image.jpg`

/** `guide/index.md` → `/guide/`, `guide/web-ui.md` → `/guide/web-ui.html`
 * (cleanUrls is off, see below). */
function pageUrl(relativePath: string): string {
  const path = relativePath.replace(/(^|\/)index\.md$/, '$1').replace(/\.md$/, '.html')
  return `${siteUrl}/${path}`
}

// `withMermaid` renders ```mermaid blocks (the diagrams in the manual) in
// the browser; their colours come from theme/caelum.css, not from mermaid's
// own themes, so they follow light and dark mode like everything else.
export default withMermaid(defineConfig({
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
    ['meta', { name: 'theme-color', content: '#1c305c' }],
    ['link', { rel: 'icon', href: `${base}favicon.svg` }],
    ['meta', { property: 'og:site_name', content: 'caelum' }],
    ['meta', { property: 'og:image', content: ogImage }],
    ['meta', { property: 'og:image:width', content: '1200' }],
    ['meta', { property: 'og:image:height', content: '630' }],
    ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
    ['meta', { name: 'twitter:image', content: ogImage }],
    ['meta', { name: 'author', content: DEVELOPER_NAME }],
  ],

  // Written to dist/sitemap.xml with each page's git date as <lastmod>;
  // docs/public/robots.txt points crawlers at it.
  sitemap: { hostname: `${siteUrl}/` },

  // Per page: canonical URL plus Open Graph / Twitter title, description and
  // URL. Descriptions come from each page's `description` frontmatter.
  transformHead({ pageData, title, description }) {
    if (pageData.isNotFound) return [['meta', { name: 'robots', content: 'noindex' }]]
    const url = pageUrl(pageData.relativePath)
    const head: HeadConfig[] = [
      ['link', { rel: 'canonical', href: url }],
      ['meta', { property: 'og:type', content: pageData.frontmatter.layout === 'home' ? 'website' : 'article' }],
      ['meta', { property: 'og:url', content: url }],
      ['meta', { property: 'og:title', content: title }],
      ['meta', { property: 'og:description', content: description }],
      ['meta', { name: 'twitter:title', content: title }],
      ['meta', { name: 'twitter:description', content: description }],
    ]
    if (pageData.relativePath === 'index.md') {
      head.push([
        'script',
        { type: 'application/ld+json' },
        JSON.stringify({
          '@context': 'https://schema.org',
          '@type': 'SoftwareApplication',
          name: 'caelum',
          description,
          url: `${siteUrl}/`,
          applicationCategory: 'ScientificApplication',
          operatingSystem: 'Linux (Raspberry Pi OS)',
          // `codeRepository` belongs to SoftwareSourceCode, not to
          // SoftwareApplication — validators flag it here; sameAs is valid.
          sameAs: ['https://github.com/roman-dvorak/caelum'],
          offers: { '@type': 'Offer', price: '0', priceCurrency: 'EUR' },
          author: { '@type': 'Organization', name: DEVELOPER_NAME, url: DEVELOPER_URL },
          maintainer: { '@type': 'Organization', name: DEVELOPER_NAME, url: DEVELOPER_URL },
        }),
      ])
    }
    return head
  },

  themeConfig: {
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Getting started', link: '/getting-started' },
      { text: 'Manual', link: '/manual' },
      { text: 'Cameras', link: '/cameras/', activeMatch: '^/cameras/' },
      { text: 'Web viewer', link: '/viewer' },
      {
        text: 'Documentation',
        link: '/guide/',
        activeMatch: '^/(guide/|capture-programs|dng-capture-sets)',
      },
      // The maintainer, as a top-level link rather than buried in the footer.
      { text: 'AstroMeters', link: 'https://astrometers.eu' },
    ],

    socialLinks: [{ icon: 'github', link: 'https://github.com/roman-dvorak/caelum' }],

    editLink: {
      pattern: 'https://github.com/roman-dvorak/caelum/edit/master/docs/:path',
    },

    // One sidebar per top-level section. Getting started, the manual and the
    // web viewer are single pages with their own outline (`sidebar: false`).
    sidebar: {
      '/cameras/': [
        {
          text: 'Cameras',
          items: [
            { text: 'Supported cameras', link: '/cameras/' },
            { text: 'AMASC01', link: '/cameras/amasc01' },
            { text: 'DIY cameras', link: '/cameras/diy' },
          ],
        },
      ],
      '/': [
        {
          text: 'Overview',
          items: [
            { text: 'Introduction', link: '/guide/' },
            { text: 'Installation', link: '/guide/installation' },
            { text: 'Concepts', link: '/guide/concepts' },
          ],
        },
        {
          text: 'Running a camera',
          items: [
            { text: 'Camera backends', link: '/guide/cameras' },
            { text: 'Exposure control', link: '/guide/exposure' },
            { text: 'Storage & retention', link: '/guide/storage' },
            { text: 'Upload & archive', link: '/guide/upload' },
          ],
        },
        {
          text: 'Operating',
          items: [
            { text: 'Web interface', link: '/guide/web-ui' },
            { text: 'Configuration files', link: '/guide/config-files' },
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
            { text: 'Running from source', link: '/guide/development' },
          ],
        },
      ],
    },

    // Bundled at build time — no external service, so the docs stay fully
    // self-hosted and work on a LAN-only mirror.
    search: { provider: 'local' },

    outline: { level: [2, 3] },

    footer: {
      message:
        'caelum is developed and maintained by <a href="https://astrometers.eu">AstroMeters</a>' +
        // Reopens the consent banner (theme/ConsentBanner.vue); hidden by CSS
        // where analytics is off, i.e. anywhere but the public site. A button,
        // not a link: VitePress' router would turn a hash link into navigation.
        '<span class="cookie-settings"> · <button type="button">Cookie settings</button></span>',
      copyright: '© AstroMeters',
    },
  },

  // Diagram snippets shared by several pages (`<!--@include: ...-->`); not
  // pages themselves.
  srcExclude: ['_diagrams/**'],

  mermaid: {
    // Plain base styles; caelum.css recolours nodes, edges and labels from
    // the theme tokens.
    theme: 'base',
    themeVariables: { fontFamily: "'Inter Variable', Inter, system-ui, sans-serif", fontSize: '14px' },
    flowchart: { curve: 'basis', padding: 14, nodeSpacing: 40, rankSpacing: 50 },
  },
}))

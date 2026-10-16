/**
 * Google Analytics and Microsoft Clarity, loaded only after the visitor
 * consents (GDPR / ePrivacy) and only on the public site.
 *
 * The IDs are not secrets: both end up in every page's HTML by design.
 *
 * `ANALYTICS_HOST` keeps the same build tracker-free wherever else it is
 * served — `vitepress dev`, `vitepress preview`, or an Apache mirror on a LAN
 * (scripts/deploy-static.sh). There is no banner there either, since there is
 * nothing to consent to.
 */
export const ANALYTICS_HOST = 'caelum.astrometers.eu'

/** The astrometers.eu GA4 property — shared on purpose, so a visitor moving
 * between the product site and the docs is one user. Filter by hostname to
 * report on the docs alone. */
export const GA_ID = 'G-NBPYLMPRY4'

/** For now the astrometers.eu Clarity project; a project of its own would
 * keep the docs' heatmaps apart from the product site. Empty = not loaded. */
export const CLARITY_ID = 'sofpwcakki'

export type Consent = 'granted' | 'denied'

const STORAGE_KEY = 'caelum-docs-consent'

export function analyticsEnabled(): boolean {
  return location.hostname === ANALYTICS_HOST
}

export function trackerNames(): string[] {
  return [GA_ID && 'Google Analytics', CLARITY_ID && 'Microsoft Clarity'].filter(Boolean) as string[]
}

export function storedConsent(): Consent | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return v === 'granted' || v === 'denied' ? v : null
  } catch {
    return null
  }
}

/** Records the choice and applies it. Withdrawing a previous "granted" drops
 * the trackers' cookies and reloads, since neither script can be unloaded. */
export function setConsent(value: Consent) {
  const previous = storedConsent()
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // Private mode etc.: the choice holds for this page view only.
  }
  if (value === 'granted') {
    loadTrackers()
  } else if (previous === 'granted') {
    deleteTrackerCookies()
    location.reload()
  }
}

let loaded = false

export function loadTrackers() {
  if (loaded) return
  loaded = true
  const w = window as any

  if (GA_ID) {
    w.dataLayer = w.dataLayer || []
    w.gtag = function gtag() {
      w.dataLayer.push(arguments)
    }
    w.gtag('js', new Date())
    // Page changes inside the SPA are picked up by GA4's enhanced
    // measurement (history events), which is on by default.
    w.gtag('config', GA_ID)
    addScript(`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`)
  }

  if (CLARITY_ID) {
    w.clarity =
      w.clarity ||
      function clarity() {
        ;(w.clarity.q = w.clarity.q || []).push(arguments)
      }
    addScript(`https://www.clarity.ms/tag/${CLARITY_ID}`)
  }
}

function addScript(src: string) {
  const s = document.createElement('script')
  s.async = true
  s.src = src
  document.head.appendChild(s)
}

const TRACKER_COOKIE = /^(_ga|_gid|_gat|_clck|_clsk|CLID|MUID)/

function deleteTrackerCookies() {
  // GA sets its cookies on the registrable domain (.astrometers.eu), so try
  // that as well as the host itself.
  const host = location.hostname
  const domains = [host, host.split('.').slice(-2).join('.')]
  for (const c of document.cookie.split(';')) {
    const name = c.split('=')[0].trim()
    if (!TRACKER_COOKIE.test(name)) continue
    for (const d of domains) {
      document.cookie = `${name}=; Max-Age=0; path=/; domain=${d}`
    }
    document.cookie = `${name}=; Max-Age=0; path=/`
  }
}

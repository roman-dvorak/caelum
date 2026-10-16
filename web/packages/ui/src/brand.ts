/** Fixed product facts shared by every app — deliberately not configuration. */

/** Public documentation site. The UI deep-links to `/guide/security.html`
 * and `/guide/concepts.html` — renaming those pages breaks the links. */
export const DOCS_URL = 'https://caelum.astrometers.eu'

/** The developer of the system, credited in the sidebar footer. */
export const DEVELOPER_NAME = 'AstroMeters'
export const DEVELOPER_URL = 'https://astrometers.eu'

// Replaced at build time by each app's vite.config.ts (`define`, from
// web/build-info.ts): the package version and the commit it was built from.
declare const __CAELUM_VERSION__: string
declare const __CAELUM_BUILD__: string

export const BUILD_INFO = {
  version: typeof __CAELUM_VERSION__ === 'string' ? __CAELUM_VERSION__ : 'dev',
  build: typeof __CAELUM_BUILD__ === 'string' ? __CAELUM_BUILD__ : 'unknown',
}

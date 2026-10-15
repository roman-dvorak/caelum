import { LocalApiClient } from '@caelum/api-client'

/**
 * Single shared client instance for the whole app. Same-origin (empty
 * baseUrl) works both behind the Vite dev proxy (see vite.config.ts) and in
 * the production build, which is served by the caelum backend itself.
 */
export const localApiClient = new LocalApiClient()

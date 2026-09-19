import { RemoteApiClient } from '@caelum/api-client'

/**
 * Directory this document was served from, e.g. "/" at a document root or
 * "/allsky/" in a subdirectory.
 *
 * caelum's uploader rsyncs the data tree (`cameras.json`, `<slug>/…`) next
 * to this app's `index.html`, so that directory *is* the data root. Deriving
 * it at runtime rather than hardcoding "/" means one build works wherever
 * the folder is dropped, with no rebuild and no Apache configuration.
 *
 * Safe despite being computed from the URL because the app uses HashRouter:
 * client-side routes live in the fragment, so `location.pathname` is the
 * index.html's own directory no matter which route is open.
 */
function documentDirectory(): string {
  return window.location.pathname.replace(/[^/]*$/, '')
}

// Override via .env only when the data tree is hosted somewhere else
// entirely — e.g. pointing a dev server at a production archive. See
// .env.example.
const baseUrl = import.meta.env.VITE_REMOTE_BASE_URL || documentDirectory()

export const remoteApiClient = new RemoteApiClient({ baseUrl })

import { RemoteApiClient } from '@caelum/api-client'

// Defaults to same-origin "/", which is correct once this app's dist/ is
// deployed at the Apache document root next to the data tree caelum's
// uploader rsyncs there. Override via .env for pointing dev at a
// separately-hosted data tree — see .env.example.
const baseUrl = import.meta.env.VITE_REMOTE_BASE_URL || '/'

export const remoteApiClient = new RemoteApiClient({ baseUrl })

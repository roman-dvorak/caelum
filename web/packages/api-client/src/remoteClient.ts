/**
 * Typed client for the read-only static-file API `apps/remote-web` consumes.
 * There is no backend here at all — every method is a plain `fetch()` of a
 * JSON file that caelum's uploader rsyncs to an Apache document root. All
 * paths are resolved relative to a configurable base URL.
 */

import type { CameraManifest, CamerasIndex, DateIndex, FrameMetadata } from './types.js'

export interface RemoteApiClientOptions {
  /**
   * Root the static data tree is served from, e.g. "https://allsky.example.org/data/"
   * or "/" for same-origin (the default — right for when remote-web is
   * itself deployed at the Apache document root next to the data tree).
   */
  baseUrl?: string
}

export class RemoteApiClientError extends Error {
  readonly status: number
  readonly url: string

  constructor(message: string, status: number, url: string) {
    super(message)
    this.name = 'RemoteApiClientError'
    this.status = status
    this.url = url
  }
}

function normalizeBaseUrl(base: string): string {
  const trimmed = base.trim()
  const withValue = trimmed.length > 0 ? trimmed : '/'
  const withTrailingSlash = withValue.endsWith('/') ? withValue : `${withValue}/`
  // Absolute URLs (http/https) are used as-is; anything else is treated as
  // a site-absolute path so fetches don't resolve relative to whatever
  // client-side route the SPA currently happens to be on.
  if (/^https?:\/\//i.test(withTrailingSlash)) return withTrailingSlash
  return withTrailingSlash.startsWith('/') ? withTrailingSlash : `/${withTrailingSlash}`
}

function joinPath(base: string, ...segments: string[]): string {
  const cleanSegments = segments
    .flatMap((segment) => segment.split('/'))
    .filter((part) => part.length > 0)
  return base + cleanSegments.join('/')
}

export class RemoteApiClient {
  private readonly baseUrl: string

  constructor(options: RemoteApiClientOptions = {}) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl ?? '/')
  }

  private async fetchJson<T>(url: string): Promise<T> {
    const res = await fetch(url)
    if (!res.ok) {
      throw new RemoteApiClientError(`Failed to fetch ${url}: ${res.status}`, res.status, url)
    }
    return (await res.json()) as T
  }

  /** Resolve a path relative to the data root (e.g. a `CameraSummary.manifest`
   * or `.latest_thumbnail` value, both already `<slug>/...`-prefixed). */
  resolveUrl(relativePath: string): string {
    return joinPath(this.baseUrl, relativePath)
  }

  /** Resolve a path relative to one camera's own prefix (e.g. a manifest
   * date entry's or index.json image's `thumbnail`/`metadata` value). */
  resolveCameraUrl(slug: string, relativePath: string): string {
    return joinPath(this.baseUrl, slug, relativePath)
  }

  getCameras(): Promise<CamerasIndex> {
    return this.fetchJson<CamerasIndex>(this.resolveUrl('cameras.json'))
  }

  getCameraManifest(slug: string): Promise<CameraManifest> {
    return this.fetchJson<CameraManifest>(this.resolveCameraUrl(slug, 'manifest.json'))
  }

  /** Fetched lazily — only call this once a specific date is opened.
   * `date` is the manifest's `YYYY-MM-DD`; on disk it is nested
   * `YYYY/MM/DD`. */
  getDateIndex(slug: string, date: string): Promise<DateIndex> {
    return this.fetchJson<DateIndex>(this.resolveCameraUrl(slug, `thumbnails/${date.replaceAll('-', '/')}/index.json`))
  }

  /** `relativeMetadataPath` is a `DateIndexImageEntry.metadata` value, e.g.
   * "thumbnails/20260101/221530.json". */
  getFrameMetadata(slug: string, relativeMetadataPath: string): Promise<FrameMetadata> {
    return this.fetchJson<FrameMetadata>(this.resolveCameraUrl(slug, relativeMetadataPath))
  }

  /** May 404 — the backend only produces a keogram once a night's worth of
   * frames exist, so it is normal for this to be absent for a given date. */
  keogramUrl(slug: string, date: string): string {
    return this.resolveCameraUrl(slug, `derivatives/${date}/keogram.png`)
  }
}

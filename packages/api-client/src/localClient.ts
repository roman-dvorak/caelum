/**
 * Typed client for caelum's live local REST + WebSocket API. Used only by
 * `apps/local-web`, which talks to the caelum backend running on the same
 * device (e.g. a Raspberry Pi), same-origin in production and via the Vite
 * dev proxy in development.
 */

import type {
  AppConfig,
  CameraModeResponse,
  DeepPartial,
  ExposureOverrideRequest,
  ExposureOverrideResponse,
  FrameMetadata,
  PluginConfig,
  PluginUpdateRequest,
  PluginsResponse,
  SkyStateResponse,
  StatusResponse,
} from './types.js'

export interface LocalApiClientOptions {
  /**
   * Origin to prefix REST/WS requests with, e.g. "http://raspberrypi.local:8000".
   * Defaults to "" (same-origin relative requests), which is what you want
   * both behind the Vite dev proxy and in the production build served by
   * FastAPI itself.
   */
  baseUrl?: string
}

export class LocalApiClientError extends Error {
  readonly status: number
  readonly path: string

  constructor(message: string, status: number, path: string) {
    super(message)
    this.name = 'LocalApiClientError'
    this.status = status
    this.path = path
  }
}

export class LocalApiClient {
  private readonly baseUrl: string

  constructor(options: LocalApiClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? ''
  }

  private apiUrl(path: string): string {
    return `${this.baseUrl}/api${path}`
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(this.apiUrl(path), init)
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      throw new LocalApiClientError(
        `caelum API request failed: ${init?.method ?? 'GET'} ${path} -> ${res.status}${detail ? ` (${detail})` : ''}`,
        res.status,
        path,
      )
    }
    return (await res.json()) as T
  }

  private async postJson<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  }

  getStatus(): Promise<StatusResponse> {
    return this.request<StatusResponse>('/status')
  }

  getSkyState(): Promise<SkyStateResponse> {
    return this.request<SkyStateResponse>('/skystate')
  }

  getConfig(): Promise<AppConfig> {
    return this.request<AppConfig>('/config')
  }

  /** Deep-merged server-side — only send the fields that changed. */
  updateConfig(patch: DeepPartial<AppConfig>): Promise<AppConfig> {
    return this.request<AppConfig>('/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ patch }),
    })
  }

  setCameraMode(streamMode: boolean): Promise<CameraModeResponse> {
    return this.postJson<CameraModeResponse>('/camera/mode', { stream_mode: streamMode })
  }

  setExposureOverride(body: ExposureOverrideRequest): Promise<ExposureOverrideResponse> {
    return this.postJson<ExposureOverrideResponse>('/camera/exposure-override', body)
  }

  clearExposureOverride(): Promise<ExposureOverrideResponse> {
    return this.postJson<ExposureOverrideResponse>('/camera/exposure-override', { clear: true })
  }

  getPlugins(): Promise<PluginsResponse> {
    return this.request<PluginsResponse>('/plugins')
  }

  updatePlugin(pluginId: string, patch: PluginUpdateRequest): Promise<PluginConfig> {
    return this.request<PluginConfig>(`/plugins/${encodeURIComponent(pluginId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
  }

  /** URL for the raw latest-frame JPEG (404 if nothing captured yet). Not
   * used for the live view (see `connectFrameStream`) but handy as a
   * fallback/poster image before the first WS frame arrives. */
  latestFrameUrl(): string {
    return this.apiUrl('/frame/latest.jpg')
  }
}

// ---- /ws/stream ---------------------------------------------------------

/** One decoded frame pushed by `/ws/stream`: metadata plus an object URL
 * for the JPEG bytes that arrived alongside it. */
export interface StreamFrame {
  metadata: FrameMetadata
  /** `URL.createObjectURL` result — revoked automatically when the next
   * frame arrives or the stream is closed. Do not hold onto it. */
  imageBlobUrl: string
}

export interface FrameStreamOptions {
  /** Full ws:// or wss:// URL. Defaults to same-origin `/ws/stream`,
   * matching the Vite dev proxy and the production same-origin deployment. */
  url?: string
  onFrame: (frame: StreamFrame) => void
  onOpen?: () => void
  onError?: (event: Event) => void
  onClose?: (event: CloseEvent) => void
}

export interface FrameStreamHandle {
  close: () => void
}

function defaultStreamUrl(): string {
  if (typeof window === 'undefined') {
    throw new Error('connectFrameStream() requires a browser environment or an explicit `url`')
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/stream`
}

/**
 * Connects to `/ws/stream` and decodes the alternating (text metadata,
 * binary JPEG) frame pairs the backend sends. Each JPEG becomes a fresh
 * blob URL; the previous one is revoked as soon as a new frame lands (or
 * the connection closes) so long-running sessions don't leak memory.
 */
export function connectFrameStream(options: FrameStreamOptions): FrameStreamHandle {
  const ws = new WebSocket(options.url ?? defaultStreamUrl())
  ws.binaryType = 'arraybuffer'

  let pendingMetadata: FrameMetadata | null = null
  let lastBlobUrl: string | null = null

  const revokeLast = () => {
    if (lastBlobUrl) {
      URL.revokeObjectURL(lastBlobUrl)
      lastBlobUrl = null
    }
  }

  ws.onopen = () => {
    options.onOpen?.()
  }

  ws.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
    if (typeof event.data === 'string') {
      // Text frame: metadata for the image binary frame that follows.
      try {
        pendingMetadata = JSON.parse(event.data) as FrameMetadata
      } catch {
        pendingMetadata = null
      }
      return
    }

    // Binary frame: the JPEG for the metadata we just received. Frames
    // always arrive as a strict (text, binary) pair, so if we somehow get
    // a binary frame without a preceding metadata frame, drop it rather
    // than emit a mismatched pair.
    if (!pendingMetadata) return
    const blob = new Blob([event.data], { type: 'image/jpeg' })
    const url = URL.createObjectURL(blob)
    revokeLast()
    lastBlobUrl = url
    options.onFrame({ metadata: pendingMetadata, imageBlobUrl: url })
    pendingMetadata = null
  }

  ws.onerror = (event) => {
    options.onError?.(event)
  }

  ws.onclose = (event) => {
    revokeLast()
    options.onClose?.(event)
  }

  return {
    close: () => {
      revokeLast()
      ws.close()
    },
  }
}

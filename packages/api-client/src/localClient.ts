/**
 * Typed client for caelum's live local REST + WebSocket API. Used only by
 * `apps/local-web`, which talks to the caelum backend running on the same
 * device (e.g. a Raspberry Pi), same-origin in production and via the Vite
 * dev proxy in development.
 */

import type {
  AppConfig,
  AuthContext,
  CameraModeResponse,
  DeepPartial,
  DeleteFramesRequest,
  DirectoryListing,
  ExposureOverrideRequest,
  ExposureOverrideResponse,
  FrameListResponse,
  FrameMetadata,
  FrameDateSummary,
  PluginConfig,
  PluginUpdateRequest,
  PluginsResponse,
  Role,
  SkyStateResponse,
  StatusResponse,
  UsageResponse,
  UserSummary,
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
    // `credentials: 'include'` so the session cookie travels even when a dev
    // frontend points at a camera on another origin; same-origin requests
    // are unaffected.
    const res = await fetch(this.apiUrl(path), { credentials: 'include', ...init })
    if (!res.ok) {
      const detail = await this.errorDetail(res)
      throw new LocalApiClientError(
        `caelum API request failed: ${init?.method ?? 'GET'} ${path} -> ${res.status}${detail ? ` (${detail})` : ''}`,
        res.status,
        path,
      )
    }
    return (await res.json()) as T
  }

  /** FastAPI errors are `{"detail": "..."}`; surface just that when present
   * so the UI can show the backend's own wording rather than a JSON blob. */
  private async errorDetail(res: Response): Promise<string> {
    const text = await res.text().catch(() => '')
    try {
      const parsed = JSON.parse(text) as { detail?: unknown }
      if (typeof parsed.detail === 'string') return parsed.detail
    } catch {
      /* not JSON — fall through to the raw body */
    }
    return text
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

  // ---- auth --------------------------------------------------------------

  /** Unauthenticated: what this deployment requires, and who we already are. */
  getAuthContext(): Promise<AuthContext> {
    return this.request<AuthContext>('/auth/context')
  }

  login(username: string, password: string): Promise<AuthContext> {
    return this.postJson<AuthContext>('/auth/login', { username, password })
  }

  logout(): Promise<{ ok: boolean }> {
    return this.postJson<{ ok: boolean }>('/auth/logout', {})
  }

  changePassword(currentPassword: string, newPassword: string): Promise<{ ok: boolean }> {
    return this.postJson<{ ok: boolean }>('/auth/password', {
      current_password: currentPassword,
      new_password: newPassword,
    })
  }

  listUsers(): Promise<UserSummary[]> {
    return this.request<UserSummary[]>('/auth/users')
  }

  createUser(username: string, password: string, role: Role): Promise<UserSummary> {
    return this.postJson<UserSummary>('/auth/users', { username, password, role })
  }

  updateUser(username: string, patch: { role?: Role; password?: string }): Promise<UserSummary> {
    return this.request<UserSummary>(`/auth/users/${encodeURIComponent(username)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
  }

  deleteUser(username: string): Promise<{ ok: boolean }> {
    return this.request<{ ok: boolean }>(`/auth/users/${encodeURIComponent(username)}`, {
      method: 'DELETE',
    })
  }

  // ---- stored output -----------------------------------------------------

  listFiles(path = ''): Promise<DirectoryListing> {
    return this.request<DirectoryListing>(`/files?path=${encodeURIComponent(path)}`)
  }

  getUsage(): Promise<UsageResponse> {
    return this.request<UsageResponse>('/files/usage')
  }

  deletePath(path: string): Promise<{ deleted: string; files_removed: number }> {
    return this.request(`/files?path=${encodeURIComponent(path)}`, { method: 'DELETE' })
  }

  /** Direct URL for an `<img>`/`<a>` — these are plain GETs the browser
   * makes itself, carrying the session cookie like any other request. */
  fileContentUrl(path: string, download = false): string {
    return this.apiUrl(`/files/content?path=${encodeURIComponent(path)}${download ? '&download=true' : ''}`)
  }

  /** Server-rendered PNG, the only way to see a FITS frame in a browser. */
  filePreviewUrl(path: string, maxDim = 1024): string {
    return this.apiUrl(`/files/preview?path=${encodeURIComponent(path)}&max_dim=${maxDim}`)
  }

  // ---- recordings --------------------------------------------------------

  listFrameDates(): Promise<FrameDateSummary[]> {
    return this.request<FrameDateSummary[]>('/frames/dates')
  }

  listFrames(date: string): Promise<FrameListResponse> {
    return this.request<FrameListResponse>(`/frames?date=${encodeURIComponent(date)}`)
  }

  deleteFrames(body: DeleteFramesRequest): Promise<{ date: string; files_removed: number }> {
    return this.request('/frames', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
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

// ---- /ws/terminal --------------------------------------------------------

export interface TerminalSessionOptions {
  /** Full ws:// or wss:// URL. Defaults to same-origin `/ws/terminal`. */
  url?: string
  /** Raw PTY output. Bytes, not text: a UTF-8 sequence can straddle a read
   * boundary on the backend, so decoding is xterm.js's job, not ours. */
  onData: (chunk: Uint8Array) => void
  onOpen?: () => void
  onClose?: (event: CloseEvent) => void
  onError?: (event: Event) => void
}

export interface TerminalSessionHandle {
  /** Keystrokes from the terminal widget. */
  send: (data: string) => void
  /** Tell the PTY its new window size so full-screen programs reflow. */
  resize: (cols: number, rows: number) => void
  close: () => void
}

function defaultTerminalUrl(): string {
  if (typeof window === 'undefined') {
    throw new Error('connectTerminal() requires a browser environment or an explicit `url`')
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/terminal`
}

/**
 * Opens an interactive shell session on the backend.
 *
 * Note there is no token to pass: the browser attaches the session cookie to
 * the WebSocket handshake automatically, and the backend rejects the upgrade
 * with a 403 for anyone who is not an admin (or if the terminal is disabled
 * in config), so a failure surfaces as `onClose`/`onError` rather than an
 * open socket that then does nothing.
 */
export function connectTerminal(options: TerminalSessionOptions): TerminalSessionHandle {
  const ws = new WebSocket(options.url ?? defaultTerminalUrl())
  ws.binaryType = 'arraybuffer'

  ws.onopen = () => options.onOpen?.()
  ws.onerror = (event) => options.onError?.(event)
  ws.onclose = (event) => options.onClose?.(event)
  ws.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
    if (typeof event.data === 'string') return
    options.onData(new Uint8Array(event.data))
  }

  const post = (message: unknown) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message))
  }

  return {
    send: (data) => post({ type: 'input', data }),
    resize: (cols, rows) => post({ type: 'resize', cols, rows }),
    close: () => ws.close(),
  }
}

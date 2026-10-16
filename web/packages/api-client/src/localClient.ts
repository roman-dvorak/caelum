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
  CameraOptions,
  DeepPartial,
  DeleteFramesRequest,
  DerivativeKindSummary,
  DerivativeListResponse,
  DirectoryListing,
  ExposureOverrideRequest,
  ExposureOverrideResponse,
  FrameListResponse,
  ListDerivativesParams,
  ListFramesParams,
  ObservationNightSummary,
  FrameMetadata,
  FrameDateSummary,
  LogEntry,
  PluginConfig,
  PluginUpdateRequest,
  PluginsResponse,
  Role,
  SkyStateResponse,
  StatusResponse,
  OverlayAssetInfo,
  OverlayElementDef,
  OverlayTemplate,
  SystemActionResponse,
  SystemInfoResponse,
  UpdateStatusResponse,
  UsageResponse,
  UserSummary,
  WhiteBalanceAutoCalibrateRequest,
  WhiteBalanceRequest,
  WhiteBalanceResponse,
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

  getCameraOptions(): Promise<CameraOptions> {
    return this.request<CameraOptions>('/camera/options')
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

  setWhiteBalance(body: WhiteBalanceRequest): Promise<WhiteBalanceResponse> {
    return this.postJson<WhiteBalanceResponse>('/camera/white-balance', body)
  }

  autoCalibrateWhiteBalance(body: WhiteBalanceAutoCalibrateRequest): Promise<WhiteBalanceResponse> {
    return this.postJson<WhiteBalanceResponse>('/camera/white-balance/auto-calibrate', body)
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

  /** The latest frame's camera-rendered overlay (transparent PNG). `key`
   * busts the browser cache per frame/render — pass something that changes
   * with it, e.g. `captured_at` plus the element count. */
  latestOverlayUrl(key: string): string {
    return this.apiUrl(`/frame/overlay.png?k=${encodeURIComponent(key)}`)
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

  /** UTC calendar dates — matches the on-disk layout, splits at UTC midnight. */
  listFrameDates(): Promise<FrameDateSummary[]> {
    return this.request<FrameDateSummary[]>('/frames/dates')
  }

  /** Observation nights, sunrise to sunrise — see ListFramesParams. */
  listObservationNights(): Promise<ObservationNightSummary[]> {
    return this.request<ObservationNightSummary[]>('/frames/nights')
  }

  listFrames(params: ListFramesParams): Promise<FrameListResponse> {
    const query = new URLSearchParams()
    if (params.date) query.set('date', params.date)
    if (params.night) query.set('night', params.night)
    if (params.limit) query.set('limit', String(params.limit))
    if (params.offset) query.set('offset', String(params.offset))
    return this.request<FrameListResponse>(`/frames?${query}`)
  }

  /** Which derivative kinds (keogram, keogram_live, meteor_crop, ...) exist
   * for this date/night, and how many of each — drives the Recordings
   * page's derivative sub-tabs. */
  listDerivativeKinds(params: ListFramesParams): Promise<DerivativeKindSummary[]> {
    const query = new URLSearchParams()
    if (params.date) query.set('date', params.date)
    if (params.night) query.set('night', params.night)
    return this.request<DerivativeKindSummary[]>(`/frames/derivative-kinds?${query}`)
  }

  /** Paginated, one kind at a time — a busy night's meteor crops alone can
   * number in the hundreds. */
  listDerivatives(params: ListDerivativesParams): Promise<DerivativeListResponse> {
    const query = new URLSearchParams()
    if (params.date) query.set('date', params.date)
    if (params.night) query.set('night', params.night)
    query.set('kind', params.kind)
    if (params.limit) query.set('limit', String(params.limit))
    if (params.offset) query.set('offset', String(params.offset))
    return this.request<DerivativeListResponse>(`/frames/derivatives?${query}`)
  }

  deleteFrames(body: DeleteFramesRequest): Promise<{ date: string; files_removed: number }> {
    return this.request('/frames', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  }

  // ---- logs ----------------------------------------------------------

  /** Snapshot of the in-memory ring buffer — what `/ws/logs` also sends as
   * its first message. Useful on its own for a quick curl check. */
  getLogs(): Promise<LogEntry[]> {
    return this.request<LogEntry[]>('/logs')
  }

  // ---- system --------------------------------------------------------

  getSystemInfo(): Promise<SystemInfoResponse> {
    return this.request<SystemInfoResponse>('/system/info')
  }

  shutdownSystem(): Promise<SystemActionResponse> {
    return this.postJson<SystemActionResponse>('/system/shutdown', {})
  }

  rebootSystem(): Promise<SystemActionResponse> {
    return this.postJson<SystemActionResponse>('/system/reboot', {})
  }

  // ---- software update -----------------------------------------------

  getUpdateStatus(): Promise<UpdateStatusResponse> {
    return this.request<UpdateStatusResponse>('/update/status')
  }

  /** Fetches the configured release manifest (server-side). */
  checkUpdate(): Promise<UpdateStatusResponse> {
    return this.postJson<UpdateStatusResponse>('/update/check', {})
  }

  /** Starts installing `version`, which must be the one the last check found. */
  startUpdate(version: string): Promise<UpdateStatusResponse> {
    return this.postJson<UpdateStatusResponse>('/update/start', { version })
  }

  /** Installs an uploaded `caelum-<version>-*.whl` — for cameras without internet. */
  uploadUpdate(file: File): Promise<UpdateStatusResponse> {
    const body = new FormData()
    body.append('file', file)
    return this.request<UpdateStatusResponse>('/update/upload', { method: 'POST', body })
  }

  // ---- overlay assets --------------------------------------------------

  /** Direct URL for a `custom_image` overlay element's `asset` field —
   * an `<img>`/CSS background URL the browser fetches itself, session
   * cookie included like any other same-origin request. */
  overlayAssetUrl = (asset: string): string => this.apiUrl(`/overlay/assets/${encodeURIComponent(asset)}`)

  listOverlayAssets(): Promise<OverlayAssetInfo[]> {
    return this.request<OverlayAssetInfo[]>('/overlay/assets')
  }

  uploadOverlayAsset(file: File): Promise<OverlayAssetInfo> {
    const body = new FormData()
    body.append('file', file)
    return this.request<OverlayAssetInfo>('/overlay/assets', { method: 'POST', body })
  }

  /** The overlay a new camera starts with (time, exposure and gain, camera
   * name, AstroMeters logo, software, camera model). */
  getDefaultOverlayTemplate(): Promise<OverlayTemplate> {
    return this.request<OverlayTemplate>('/overlay/default-template')
  }

  deleteOverlayAsset(name: string): Promise<{ deleted: string }> {
    return this.request(`/overlay/assets/${encodeURIComponent(name)}`, { method: 'DELETE' })
  }

  /** Renders a draft template exactly as the camera would on the latest
   * frame (with the system readouts and other plugins' elements) — a
   * transparent PNG to lay under the editor's handles. */
  async previewOverlay(elements: OverlayElementDef[]): Promise<Blob> {
    const path = '/overlay/preview.png'
    const res = await fetch(this.apiUrl(path), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(elements),
    })
    if (!res.ok) {
      const detail = await this.errorDetail(res)
      throw new LocalApiClientError(
        `caelum API request failed: POST ${path} -> ${res.status}${detail ? ` (${detail})` : ''}`,
        res.status,
        path,
      )
    }
    return res.blob()
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

// ---- /ws/logs --------------------------------------------------------

export interface LogStreamOptions {
  /** Full ws:// or wss:// URL. Defaults to same-origin `/ws/logs`. */
  url?: string
  /** Sent once on connect with everything currently in the ring buffer. */
  onBacklog: (entries: LogEntry[]) => void
  /** Sent for every line logged after the connection opened. */
  onEntry: (entry: LogEntry) => void
  onOpen?: () => void
  onClose?: (event: CloseEvent) => void
  onError?: (event: Event) => void
}

export interface LogStreamHandle {
  close: () => void
}

function defaultLogsUrl(): string {
  if (typeof window === 'undefined') {
    throw new Error('connectLogs() requires a browser environment or an explicit `url`')
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/logs`
}

/**
 * Connects to `/ws/logs` — admin-only, same session-cookie handshake as
 * `connectTerminal`. The backend sends one `{"type": "backlog", entries}`
 * message on connect, then one `{"type": "line", entry}` per line logged
 * after that; a malformed message is dropped rather than crashing the view.
 */
export function connectLogs(options: LogStreamOptions): LogStreamHandle {
  const ws = new WebSocket(options.url ?? defaultLogsUrl())

  ws.onopen = () => options.onOpen?.()
  ws.onerror = (event) => options.onError?.(event)
  ws.onclose = (event) => options.onClose?.(event)
  ws.onmessage = (event: MessageEvent<string>) => {
    let message: { type?: string; entries?: LogEntry[]; entry?: LogEntry }
    try {
      message = JSON.parse(event.data) as typeof message
    } catch {
      return
    }
    if (message.type === 'backlog' && message.entries) options.onBacklog(message.entries)
    else if (message.type === 'line' && message.entry) options.onEntry(message.entry)
  }

  return { close: () => ws.close() }
}

// ---- /ws/update ------------------------------------------------------

/**
 * The software-update install log: same frame protocol as `/ws/logs`
 * (backlog, then one line at a time), from the update job's own buffer.
 */
export function connectUpdateLog(options: LogStreamOptions): LogStreamHandle {
  if (options.url) return connectLogs(options)
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return connectLogs({ ...options, url: `${protocol}//${window.location.host}/ws/update` })
}

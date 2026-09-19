/**
 * Shared TypeScript types for the caelum backend contract.
 *
 * These mirror the Pydantic models in `caelum/src/caelum/api/schemas.py`,
 * `caelum/src/caelum/config/schema.py` and `caelum/src/caelum/capture/metadata.py`
 * field-for-field. Keep this file in sync if the backend contract changes.
 */

export type SkyPeriod =
  | 'day'
  | 'civil_twilight'
  | 'nautical_twilight'
  | 'astronomical_twilight'
  | 'night'

export const SKY_PERIODS: readonly SkyPeriod[] = [
  'day',
  'civil_twilight',
  'nautical_twilight',
  'astronomical_twilight',
  'night',
]

/** `GET /api/skystate` response, and the `sky_state` field of FrameMetadata. */
export interface SkyState {
  sun_altitude_deg: number
  sun_azimuth_deg: number
  moon_altitude_deg: number
  moon_azimuth_deg: number
  moon_illumination: number
  period: SkyPeriod
}

export type SkyStateResponse = SkyState

export interface FrameStats {
  mean: number
  p95: number
  p99: number
  saturated_fraction: number
  focus_score: number
}

/** `GET /api/status` response. */
export interface StatusResponse {
  camera_backend: string
  capturing: boolean
  exposure_us: number
  analogue_gain: number
  stream_mode: boolean
  manual_exposure_override: boolean
  last_capture_at: string | null
  last_stats: FrameStats | null
  last_save_raw: boolean | null
}

/**
 * One entry in `FrameMetadata.overlay_elements`. `type` is intentionally an
 * open string (not a union) so plugin-contributed overlay kinds don't
 * require a contract change here — renderers must treat unknown `type`
 * values gracefully rather than throwing.
 */
export interface OverlayElement {
  type: string
  source: string
  payload: Record<string, unknown>
}

/** The `<HHMMSS>.json` sidecar shape, and the WS text-frame payload. */
export interface FrameMetadata {
  captured_at: string
  exposure_us: number
  analogue_gain: number
  sky_state: SkyState
  focus_score: number
  overlay_elements: OverlayElement[]
}

// ---- Known overlay element payload shapes -------------------------------
// These are documented shapes for the overlay types the backend emits
// today. They are not exhaustive (plugins may introduce new ones) — treat
// them as a best-effort narrowing aid, not a closed contract.

export interface TimestampPayload {
  text: string
}

export interface ExposureReadoutPayload {
  exposure_us: number
  analogue_gain: number
}

export interface SkyStateBadgePayload {
  period: string
  sun_altitude_deg: number
  moon_illumination: number
}

export interface DetectionBoxPayload {
  /** Fractional (0..1) coordinates relative to image width/height. */
  x: number
  y: number
  w: number
  h: number
  label: string
}

// ---- AppConfig ------------------------------------------------------------

export interface CameraConfig {
  backend: 'mock' | 'picamera2' | string
  sensor_id: string
  resolution: [number, number]
}

export interface LocationConfig {
  lat: number
  lon: number
  elevation_m: number
  timezone: string
}

export interface ExposurePreset {
  exposure_us_min: number
  exposure_us_max: number
  gain_min: number
  gain_max: number
  target_mean_adu: number
  saturation_threshold: number
}

export type ExposurePolicyPresets = Record<SkyPeriod, ExposurePreset>

export interface ExposurePolicyConfig {
  presets: ExposurePolicyPresets
}

export interface StoragePolicyConfig {
  raw_periods: SkyPeriod[]
  thumbnail_max_dim: number
  jpeg_quality: number
  night_capture_interval_s: number
  day_capture_interval_s: number
  realtime_stream_fps: number
}

export interface RetentionConfig {
  max_age_days: number
  min_free_space_mb: number
  sweep_interval_s: number
}

export interface UploadConfig {
  enabled: boolean
  remote_host: string
  remote_user: string
  remote_base_path: string
  ssh_key_path: string
  camera_slug: string
  camera_name: string
  thumbnail_interval_s: number
  reconcile_interval_s: number
}

export interface RedisConfig {
  host: string
  port: number
  db: number
  key_prefix: string
}

export interface PluginConfig {
  enabled: boolean
  order: number
  settings: Record<string, unknown>
}

export type PluginsResponse = Record<string, PluginConfig>

/** Who may reach the read-only preview surface. Control endpoints are
 * always admin-only regardless of this. */
export type PreviewAccess = 'public' | 'viewer' | 'admin'

export interface AuthConfig {
  enabled: boolean
  preview_access: PreviewAccess
  session_ttl_hours: number
  terminal_enabled: boolean
}

export interface DocsConfig {
  base_url: string
}

export interface AppConfig {
  config_version: number
  camera: CameraConfig
  location: LocationConfig
  exposure_policy: ExposurePolicyConfig
  storage_policy: StoragePolicyConfig
  retention: RetentionConfig
  upload: UploadConfig
  redis: RedisConfig
  auth: AuthConfig
  docs: DocsConfig
  plugins: Record<string, PluginConfig>
}

/** Recursive partial, used for `PUT /api/config` patch bodies. */
export type DeepPartial<T> = T extends (infer U)[]
  ? DeepPartial<U>[]
  : T extends object
    ? { [K in keyof T]?: DeepPartial<T[K]> }
    : T

// ---- /api/camera/* ----------------------------------------------------

export interface CameraModeRequest {
  stream_mode: boolean
}

export interface CameraModeResponse {
  stream_mode: boolean
}

/** `GET /api/camera/options` — what this host can be pointed at. */
export interface CameraOptions {
  backends: string[]
  /** Device nodes present on the host, for the opencv backend's sensor_id. */
  v4l2_devices: string[]
  configured: CameraConfig
  /** What the capture thread currently has open. Null before the first
   * successful open; differs from `configured` while a change is pending or
   * if the new camera cannot be opened. */
  active: CameraConfig | null
  active_backend_class: string
  applied: boolean
}

export interface ExposureOverrideRequest {
  exposure_us?: number
  analogue_gain?: number
  clear?: boolean
}

export interface ExposureOverrideValue {
  exposure_us: number
  analogue_gain: number
}

export interface ExposureOverrideResponse {
  override: ExposureOverrideValue | null
}

// ---- /api/plugins/* -----------------------------------------------------

export interface PluginUpdateRequest {
  enabled?: boolean
  order?: number
  settings?: Record<string, unknown>
}

// ---- Remote static file shapes (served from the Apache upload target) ---

export interface CameraSummary {
  slug: string
  name: string
  /** Path relative to the data root, e.g. "<slug>/manifest.json". */
  manifest: string
  /** Path relative to the data root, e.g. "<slug>/thumbnails/<date>/<HHMMSS>.jpg". */
  latest_thumbnail: string | null
}

/** `<baseUrl>/cameras.json` */
export interface CamerasIndex {
  version: number
  updated_at: string
  cameras: CameraSummary[]
}

export interface CameraManifestDateEntry {
  date: string
  thumbnail_count: number
  has_raw: boolean
  raw_count: number
  /** Path relative to the camera's own `<slug>/` prefix. */
  latest_thumbnail: string
}

/** `<baseUrl>/<slug>/manifest.json` */
export interface CameraManifest {
  version: number
  slug: string
  name: string
  location: {
    lat: number
    lon: number
  }
  dates: CameraManifestDateEntry[]
}

export interface DateIndexImageEntry {
  time: string
  /** Path relative to the camera's own `<slug>/` prefix. */
  thumbnail: string
  /** Path relative to the camera's own `<slug>/` prefix. */
  metadata: string
}

/** `<baseUrl>/<slug>/thumbnails/<date>/index.json` */
export interface DateIndex {
  date: string
  images: DateIndexImageEntry[]
}

// ---- /api/auth/* ---------------------------------------------------------

export type Role = 'admin' | 'viewer'

/** `GET /api/auth/context` — the SPA's unauthenticated bootstrap. */
export interface AuthContext {
  auth_enabled: boolean
  preview_access: PreviewAccess
  terminal_enabled: boolean
  docs_url: string
  authenticated: boolean
  username: string | null
  role: string | null
}

/** An account as the API reports it — never includes credential material. */
export interface UserSummary {
  username: string
  role: Role
  created_at: string
  last_login_at: string | null
}

// ---- /api/files/* --------------------------------------------------------

export type MediaKind = 'image' | 'fits' | 'json' | 'text' | 'other'

export interface FileEntry {
  name: string
  /** Path relative to the data directory — what every /api/files call takes. */
  path: string
  kind: 'dir' | 'file'
  size: number
  modified_at: string
  media: MediaKind
}

export interface DirectoryListing {
  path: string
  parent: string | null
  entries: FileEntry[]
  total_bytes: number
}

export interface UsageResponse {
  by_subdir: Record<string, number>
  total_bytes: number
  disk_free_bytes: number
  disk_total_bytes: number
}

// ---- /api/frames/* -------------------------------------------------------

export interface FrameDateSummary {
  date: string
  thumbnails: number
  raws: number
  derivatives: number
  total_bytes: number
}

/** One capture, with its up-to-three files resolved back into a single row. */
export interface FrameEntry {
  time: string
  captured_at: string
  thumbnail: string | null
  raw: string | null
  metadata: string | null
  total_bytes: number
}

export interface FrameListResponse {
  date: string
  frames: FrameEntry[]
  derivatives: FileEntry[]
}

export interface DeleteFramesRequest {
  date: string
  /** Empty (or omitted) means the whole date. */
  times?: string[]
  kinds?: ('raw' | 'thumbnails' | 'derivatives')[]
}

// ---- /api/logs, /ws/logs -------------------------------------------------

export interface LogEntry {
  timestamp: string
  level: string
  logger: string
  message: string
}

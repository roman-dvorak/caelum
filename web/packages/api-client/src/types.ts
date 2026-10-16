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
  /** Median of the regulator's central brightness circle — what it regulates on. */
  median?: number
}

/** `GET /api/status` response. */
/** The exposure regulator's last cycle — mirrors `ExposureDiagnosticsResponse`
 * in `caelum/src/caelum/api/schemas.py`. Everything is in EV: image
 * brightness relative to full scale (0 EV = 255 ADU), exposure*gain as
 * log2(seconds) + log2(gain). Measurements are null before the first frame. */
export interface ExposureDiagnostics {
  sky_period: string
  target_ev: number
  deadband_ev: number
  ev_min: number
  ev_max: number
  kp: number
  ki: number
  kd: number
  measured_ev?: number | null
  p99_ev?: number | null
  error_ev?: number | null
  correction_ev?: number | null
  applied_ev?: number | null
  required_ev?: number | null
  remaining_ev?: number | null
  p_term_ev?: number | null
  i_term_ev?: number | null
  d_term_ev?: number | null
  output_ev?: number | null
  change_ev?: number | null
  ev_exposure?: number | null
  ev_gain?: number | null
  limited: 'none' | 'upper' | 'lower'
  integrating: boolean
  within_deadband: boolean
  saturated: boolean
  manual: boolean
}

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
  exposure_diagnostics: ExposureDiagnostics | null
  /** Frame-processing worker counters (pid, in-flight/dropped/failed frames, latency). */
  processing?: Record<string, unknown> | null
  /** Current spacing between captures, seconds. */
  frame_period_s?: number | null
  /** The running capture program (name, sha256, origin, failures…). */
  capture_program?: Record<string, unknown> | null
  /** IANA name from `location.timezone` (e.g. "Europe/Prague"). Every
   * timestamp elsewhere in the API is UTC; this is what to convert to and
   * label when showing a time to a human — see `formatLocalTime`. */
  timezone: string
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

export interface LensConfig {
  projection: 'equidistant_fisheye'
  center_x: number
  center_y: number
  radius: number
  azimuth_offset_deg: number
  mirror: boolean
}

export interface CameraConfig {
  backend: 'mock' | 'picamera2' | string
  sensor_id: string
  resolution: [number, number]
  lens: LensConfig
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
  /** Brightness setpoint, EV below full scale. */
  target_ev: number
  deadband_ev: number
  saturation_ev: number
  kp: number
  ki: number
  kd: number
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

/** Where the web UI looks for new releases — see `caelum/update/manifest.py`. */
export interface UpdateConfig {
  manifest_url: string
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
  update: UpdateConfig
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
  /** Set when `CAELUM_CAMERA_BACKEND` is pinning the backend regardless of
   * `configured`/`active` — the UI should explain this rather than leave a
   * selection that never "applies" looking broken. */
  backend_override: string | null
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

export interface WhiteBalanceRequest {
  red_gain: number
  blue_gain: number
}

export interface WhiteBalanceResponse {
  red_gain: number
  blue_gain: number
  auto: boolean
}

/** Fractional (0..1) patch over the latest frame to calibrate from. */
export interface WhiteBalanceAutoCalibrateRequest {
  x: number
  y: number
  w: number
  h: number
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
//
// Two ways to group frames into a "day" — see the backend's
// api/routes/frames.py module docstring for the full rationale:
//
// - date  (GET /api/frames/dates, ?date=)  — UTC calendar date, matches the
//   on-disk layout, but a session crossing UTC midnight splits across two.
// - night (GET /api/frames/nights, ?night=) — sunrise-to-sunrise, labelled
//   by the local date the preceding sunrise fell on. Stays one entry
//   regardless of UTC midnight. This is the one worth defaulting the UI to.
//
// Both take/return "YYYY-MM-DD" strings; every timestamp remains UTC.

export interface FrameDateSummary {
  date: string
  thumbnails: number
  raws: number
  derivatives: number
  total_bytes: number
}

/** Same shape, `date` means "the local date the night started on" instead
 * of a UTC calendar date. */
export type ObservationNightSummary = FrameDateSummary

/** One capture, with its up-to-three files resolved back into a single row. */
export interface FrameEntry {
  /** Full `YYYYMMDD-HHMMSS` (UTC) stem shared by all of this capture's
   * files — self-sufficient: it is what `DeleteFramesRequest.times` takes
   * back, and it is enough on its own to know which UTC date directory the
   * files live in (see `formatCaptureTime` for pulling out just the time). */
  time: string
  captured_at: string
  thumbnail: string | null
  raw: string | null
  metadata: string | null
  total_bytes: number
}

export interface FrameListResponse {
  /** Echoes whichever of `date`/`night` the request used. */
  date: string
  frames: FrameEntry[]
  /** Total frames in this date/night before `limit`/`offset` were applied. */
  total_frames: number
  limit: number
  offset: number
  /** Every UTC date this response draws from — one in date mode, up to two
   * in night mode. Lets a "delete this whole period" action bulk-delete
   * correctly without needing every page of results loaded first. */
  utc_dates: string[]
}

export interface ListFramesParams {
  /** Pass exactly one of `date` or `night`. */
  date?: string
  night?: string
  limit?: number
  offset?: number
}

export interface DeleteFramesRequest {
  /** Required when `times` is empty (the whole-date bulk-delete case);
   * ignored otherwise — each stem in `times` carries its own date. */
  date?: string
  times?: string[]
  kinds?: ('raw' | 'thumbnails' | 'derivatives')[]
}

// ---- /api/frames/derivative-kinds, /api/frames/derivatives ----------------
//
// Derivatives (keograms, meteor crops, ...) live one subdirectory per kind
// under `derivatives/<date>/`, each with a backend-generated thumbnail
// alongside the full-resolution file — paginated separately from captures
// since a busy night's meteor detections alone can number in the hundreds.

export interface DerivativeKindSummary {
  kind: string
  count: number
}

export interface DerivativeEntry {
  /** The derivative file's own stem — a unique id for this one derivative. */
  stem: string
  captured_at: string
  /** Small backend-generated JPEG for the gallery grid. */
  thumbnail: string | null
  /** Path to the full-resolution file, relative to the data directory. */
  full: string
  size: number
}

export interface DerivativeListResponse {
  kind: string
  entries: DerivativeEntry[]
  total: number
  limit: number
  offset: number
}

export interface ListDerivativesParams {
  /** Pass exactly one of `date` or `night`. */
  date?: string
  night?: string
  kind: string
  limit?: number
  offset?: number
}

// ---- /api/logs, /ws/logs -------------------------------------------------

export interface LogEntry {
  timestamp: string
  level: string
  logger: string
  message: string
}

// ---- /api/system/* --------------------------------------------------------

export interface DiskUsageInfo {
  path: string
  total_bytes: number
  used_bytes: number
  free_bytes: number
  percent: number
}

export interface NetworkInterfaceInfo {
  name: string
  is_up: boolean
  /** Null when the driver doesn't report a link speed (loopback, virtual
   * interfaces, or a link that's currently down). */
  speed_mbps: number | null
  addresses: string[]
}

export interface SystemInfoResponse {
  /** Running caelum version — changes when a web update lands. */
  version: string
  hostname: string
  uptime_s: number
  cpu_percent: number
  cpu_count: number
  /** 1/5/15-minute load average. Null on platforms without one (Windows). */
  load_avg: [number, number, number] | null
  mem_total_bytes: number
  mem_used_bytes: number
  mem_percent: number
  disks: DiskUsageInfo[]
  /** Sensor label -> degrees Celsius. Empty where the platform exposes none. */
  temperatures_c: Record<string, number>
  network: NetworkInterfaceInfo[]
}

export interface SystemActionResponse {
  ok: boolean
  message: string
}

// ---- /api/update/* --------------------------------------------------------

export type UpdateJobState = 'idle' | 'downloading' | 'installing' | 'restarting' | 'failed'

export interface UpdateResult {
  state: 'pending' | 'success' | 'rolled_back'
  /** On `rolled_back`: the version restored. Otherwise the version updated from. */
  from: string
  /** On `rolled_back`: the version that failed to start. */
  to: string
  at: string
}

export interface UpdateStatusResponse {
  current_version: string
  /** False outside a managed install (dev checkout, plain pip) — no update controls then. */
  managed: boolean
  manifest_url: string
  available: { version: string; notes: string } | null
  checked_at: string | null
  check_error: string | null
  job_state: UpdateJobState
  job_target: string | null
  job_error: string | null
  last_result: UpdateResult | null
}

// ---- /api/overlay/assets ---------------------------------------------------

export interface OverlayAssetInfo {
  name: string
  size: number
}

// ---- `overlay` / `telescope_position` plugin settings shapes ---------------
//
// Mirror `OverlaySettings`/`TelescopePositionSettings` in
// `caelum/src/caelum/derivatives/overlay.py` and `telescope_position.py`.
// `PluginConfig.settings` is `Record<string, unknown>` at the API-contract
// level (the app-level config store treats it as opaque) — these are for the
// overlay editor's own use when reading/writing those two plugins' settings.

export type OverlayElementKind = 'mask' | 'label' | 'image'

export interface OverlayElementDef {
  id: string
  kind: OverlayElementKind
  /** Fractional (0..1) top-left anchor. */
  x: number
  y: number
  /** mask/image only. */
  w?: number | null
  h?: number | null
  /** mask fill / label text color. */
  color: string
  /** mask fill opacity. */
  opacity: number
  /** label only — a placeholder template, e.g. "Exp: {exposure_us}us". */
  template?: string | null
  font_size_px?: number | null
  /** image only — a filename under `data_dir/overlay_assets/`. */
  asset?: string | null
}

export interface OverlayTemplate {
  name: string
  elements: OverlayElementDef[]
}

export interface OverlaySettings {
  templates: OverlayTemplate[]
  active_template: string | null
}

export interface TelescopePositionSettings {
  source: 'simulated'
  center_x: number
  center_y: number
  radius: number
  azimuth_offset_deg: number
  mirror: boolean
  label: string
}

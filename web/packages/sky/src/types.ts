/** The fisheye lens model: where the sky lands in the frame. Mirrors the backend's `LensConfig`. */
export type LensProjection =
  | 'equidistant_fisheye'
  | 'equisolid_fisheye'
  | 'stereographic_fisheye'
  | 'orthographic_fisheye'

export interface LensConfig {
  projection: LensProjection
  /** Fractions of the frame width / height. */
  center_x: number
  center_y: number
  /** Image circle's edge, as a fraction of the frame's shorter side. */
  radius: number
  /** Field of view across the image circle (180: its edge is the horizon). */
  fov_deg: number
  /** Roll of the image about the optical axis — against true north when the camera looks at the zenith. */
  azimuth_offset_deg: number
  mirror: boolean
  /** How far the optical axis leans from the zenith (default 0: straight up) … */
  tilt_deg?: number
  /** … and towards which compass azimuth. */
  tilt_azimuth_deg?: number
}

/** What the mount is doing — drives the crosshair's colour and caption. */
export type TelescopeStatus = 'tracking' | 'slewing' | 'idle' | 'parked' | 'disconnected' | 'error' | 'offline'

/** Where a telescope points: RA/Dec (with its epoch) or, failing that, alt/az. */
export interface TelescopePointing {
  status: TelescopeStatus
  raDeg?: number
  decDeg?: number
  /** Default "jnow" — what mount drivers report. */
  epoch?: 'j2000' | 'jnow'
  altDeg?: number
  azDeg?: number
  label?: string
}

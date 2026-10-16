import { useState } from 'react'
import { Button, ImageViewer, SkyStateBadge, StatusTile } from '@caelum/ui'
import { useFrameStream } from '../hooks/useFrameStream.ts'
import { useSkyState } from '../hooks/useSkyState.ts'
import { useStatus } from '../hooks/useStatus.ts'
import { localApiClient } from '../services/client.ts'

export function Dashboard() {
  const { status, error: statusError } = useStatus()
  const { skyState, error: skyError } = useSkyState()
  const { frame, status: streamStatus } = useFrameStream()
  const [showJson, setShowJson] = useState(false)

  const diag = status?.exposure_diagnostics ?? null

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-semibold tracking-[0.2em] text-ink-dim uppercase">Dashboard</h1>
        {skyState ? <SkyStateBadge skyState={skyState} /> : null}
      </div>

      {(statusError || skyError) && (
        <p className="border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {statusError ?? skyError}
        </p>
      )}

      <section className="overflow-hidden border border-line bg-void">
        {frame ? (
          <ImageViewer
            src={frame.imageBlobUrl}
            metadata={frame.metadata}
            alt="Live camera feed"
            resolveAssetUrl={localApiClient.overlayAssetUrl}
          />
        ) : (
          <div className="flex aspect-video items-center justify-center text-sm text-ink-faint">
            {streamStatus === 'connecting' ? 'Connecting to live stream…' : 'Waiting for first frame…'}
          </div>
        )}
      </section>

      {status ? (
        <div className="grid grid-cols-2 gap-px bg-line-soft sm:grid-cols-3 lg:grid-cols-4">
          <StatusTile label="Camera backend" value={status.camera_backend} />
          <StatusTile label="Capturing" value={status.capturing ? 'Yes' : 'No'} />
          <StatusTile label="Exposure" value={formatExposure(status.exposure_us)} />
          <StatusTile label="Gain" value={status.analogue_gain.toFixed(2)} unit="×" />
          <StatusTile label="Stream mode" value={status.stream_mode ? 'On' : 'Off'} />
          <StatusTile label="Manual override" value={status.manual_exposure_override ? 'Active' : 'Off'} />
          <StatusTile
            label="Last capture"
            value={status.last_capture_at ? new Date(status.last_capture_at).toLocaleTimeString() : '—'}
          />
          <StatusTile
            label="Focus score"
            value={status.last_stats ? status.last_stats.focus_score.toFixed(1) : '—'}
          />
        </div>
      ) : null}

      {status?.last_stats || diag ? (
        <section className="flex flex-col gap-1">
          <h2 className="text-xs font-semibold tracking-[0.15em] text-ink-faint uppercase">
            Exposure control
          </h2>
          <div className="grid grid-cols-2 gap-px bg-line-soft sm:grid-cols-3 lg:grid-cols-4">
            <StatusTile
              label="Mean pixel"
              value={status?.last_stats ? status.last_stats.mean.toFixed(1) : '—'}
              unit="ADU"
            />
            <StatusTile label="Setpoint" value={fixed(diag?.target_ev, 2)} unit="EV" />
            <StatusTile label="Measured" value={fixed(diag?.measured_ev, 2)} unit="EV" />
            <StatusTile
              label="Error vs. setpoint"
              value={diag?.error_ev != null ? formatSigned(diag.error_ev) : '—'}
              unit="EV"
            />
            <StatusTile
              label="Next correction"
              value={diag?.correction_ev != null ? formatSigned(diag.correction_ev) : '—'}
              unit="EV"
              hint={
                diag?.within_deadband
                  ? 'within deadband — holding steady'
                  : diag && diag.limited !== 'none'
                    ? `at the ${diag.limited} exposure limit`
                    : undefined
              }
            />
            <StatusTile
              label="p99"
              value={status?.last_stats ? status.last_stats.p99.toFixed(1) : '—'}
              unit="ADU"
            />
            <StatusTile
              label="Saturated"
              value={status?.last_stats ? (status.last_stats.saturated_fraction * 100).toFixed(1) : '—'}
              unit="%"
            />
            <StatusTile label="Deadband" value={fixed(diag?.deadband_ev, 2)} unit="EV" />
            <StatusTile
              label="PID (Kp / Ki / Kd)"
              value={diag ? `${diag.kp} / ${diag.ki} / ${diag.kd}` : '—'}
            />
          </div>
        </section>
      ) : null}

      {frame ? (
        <section className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold tracking-[0.15em] text-ink-faint uppercase">
              Frame metadata
            </h2>
            <Button variant="ghost" onClick={() => setShowJson((v) => !v)}>
              {showJson ? 'Hide JSON' : 'Show JSON'}
            </Button>
          </div>
          {showJson ? (
            <pre className="max-h-96 overflow-auto border border-line bg-void p-3 font-mono text-xs text-ink-dim">
              {JSON.stringify(
                { metadata: frame.metadata, stats: status?.last_stats ?? null, exposure: diag },
                null,
                2,
              )}
            </pre>
          ) : (
            <div className="grid grid-cols-2 gap-px bg-line-soft sm:grid-cols-3 lg:grid-cols-4">
              <StatusTile label="Captured at" value={new Date(frame.metadata.captured_at).toLocaleTimeString()} />
              <StatusTile label="Exposure" value={formatExposure(frame.metadata.exposure_us)} />
              <StatusTile label="Gain" value={frame.metadata.analogue_gain.toFixed(2)} unit="×" />
              <StatusTile label="Sky period" value={frame.metadata.sky_state.period.replaceAll('_', ' ')} />
              <StatusTile label="Sun altitude" value={frame.metadata.sky_state.sun_altitude_deg.toFixed(1)} unit="°" />
              <StatusTile label="Moon altitude" value={frame.metadata.sky_state.moon_altitude_deg.toFixed(1)} unit="°" />
              <StatusTile
                label="Moon illumination"
                value={(frame.metadata.sky_state.moon_illumination * 100).toFixed(0)}
                unit="%"
              />
              <StatusTile label="Focus score" value={frame.metadata.focus_score.toFixed(1)} />
              <StatusTile label="Overlay elements" value={String(frame.metadata.overlay_elements.length)} />
            </div>
          )}
        </section>
      ) : null}
    </div>
  )
}

function formatExposure(exposureUs: number): string {
  if (exposureUs >= 1_000_000) return `${(exposureUs / 1_000_000).toFixed(2)} s`
  if (exposureUs >= 1_000) return `${(exposureUs / 1_000).toFixed(1)} ms`
  return `${exposureUs} µs`
}

function formatSigned(value: number): string {
  const rounded = value.toFixed(2)
  return value > 0 ? `+${rounded}` : rounded
}

/** `—` for a value the backend didn't send (older/newer API, first frame). */
function fixed(value: number | null | undefined, digits: number): string {
  return typeof value === 'number' ? value.toFixed(digits) : '—'
}

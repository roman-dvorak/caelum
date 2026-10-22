import { useState } from 'react'
import {
  Button,
  ImageViewer,
  LiveFrame,
  Message,
  MetricGrid,
  PageHeader,
  SectionHeading,
  SkyStateBadge,
  StatusBadge,
  StatusTile,
} from '@caelum/ui'
import { useFrameStream } from '../hooks/useFrameStream.ts'
import { useLiveOverlay } from '../hooks/useLiveOverlay.ts'
import { useSkyState } from '../hooks/useSkyState.ts'
import { useStatus } from '../hooks/useStatus.ts'

export function Dashboard() {
  const { status, error: statusError } = useStatus()
  const { skyState, error: skyError } = useSkyState()
  const { frame, status: streamStatus } = useFrameStream()
  const overlaySrc = useLiveOverlay(frame?.metadata)
  const [showJson, setShowJson] = useState(false)

  const diag = status?.exposure_diagnostics ?? null

  return (
    <div className="flex flex-col gap-6">
      <div>
        <PageHeader
          title="Dashboard"
          actions={
            <>
              {status ? (
                <StatusBadge tone={status.capturing ? 'live' : 'neutral'}>
                  {status.capturing ? 'Capturing' : 'Idle'}
                </StatusBadge>
              ) : null}
              {skyState ? <SkyStateBadge skyState={skyState} /> : null}
            </>
          }
        />
        {statusError || skyError ? <Message kind="error">{statusError ?? skyError}</Message> : null}
      </div>

      <LiveFrame live={!!status?.capturing && !!frame}>
        {frame ? (
          <ImageViewer
            src={frame.imageBlobUrl}
            overlaySrc={overlaySrc}
            alt="Live camera feed"
          />
        ) : (
          <div className="flex aspect-video items-center justify-center text-sm text-ink-muted">
            {streamStatus === 'connecting' ? 'Connecting to live stream…' : 'Waiting for first frame…'}
          </div>
        )}
      </LiveFrame>

      {status ? (
        <MetricGrid>
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
        </MetricGrid>
      ) : null}

      {status?.last_stats || diag ? (
        <section className="flex flex-col gap-3">
          <SectionHeading>Exposure control</SectionHeading>
          <MetricGrid>
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
          </MetricGrid>
        </section>
      ) : null}

      {frame ? (
        <section className="flex flex-col gap-3">
          <SectionHeading
            actions={
              <Button variant="ghost" onClick={() => setShowJson((v) => !v)}>
                {showJson ? 'Hide JSON' : 'Show JSON'}
              </Button>
            }
          >
            Frame metadata
          </SectionHeading>
          {showJson ? (
            <pre className="max-h-96 overflow-auto rounded-sm border border-border bg-surface-0 p-3 font-mono text-code-sm text-ink-muted">
              {JSON.stringify(
                { metadata: frame.metadata, stats: status?.last_stats ?? null, exposure: diag },
                null,
                2,
              )}
            </pre>
          ) : (
            <MetricGrid>
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
            </MetricGrid>
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

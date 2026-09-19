import { ImageViewer, SkyStateBadge, StatusTile } from '@caelum/ui'
import { useFrameStream } from '../hooks/useFrameStream.ts'
import { useSkyState } from '../hooks/useSkyState.ts'
import { useStatus } from '../hooks/useStatus.ts'

export function Dashboard() {
  const { status, error: statusError } = useStatus()
  const { skyState, error: skyError } = useSkyState()
  const { frame, status: streamStatus } = useFrameStream()

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-100">Dashboard</h1>
        {skyState ? <SkyStateBadge skyState={skyState} /> : null}
      </div>

      {(statusError || skyError) && (
        <p className="rounded-md border border-red-900 bg-red-950/60 px-3 py-2 text-sm text-red-300">
          {statusError ?? skyError}
        </p>
      )}

      <section className="overflow-hidden rounded-lg border border-slate-800 bg-black">
        {frame ? (
          <ImageViewer src={frame.imageBlobUrl} metadata={frame.metadata} alt="Live camera feed" />
        ) : (
          <div className="flex aspect-video items-center justify-center text-sm text-slate-500">
            {streamStatus === 'connecting' ? 'Connecting to live stream…' : 'Waiting for first frame…'}
          </div>
        )}
      </section>

      {status ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
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
    </div>
  )
}

function formatExposure(exposureUs: number): string {
  if (exposureUs >= 1_000_000) return `${(exposureUs / 1_000_000).toFixed(2)} s`
  if (exposureUs >= 1_000) return `${(exposureUs / 1_000).toFixed(1)} ms`
  return `${exposureUs} µs`
}

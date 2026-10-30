import { useState } from 'react'
import { Button, Field, ImageViewer, LiveFrame, Message, PageHeader, Panel, StatusBadge, inputClass } from '@caelum/ui'
import { useFrameStream } from '../hooks/useFrameStream.ts'
import { useLiveOverlay } from '../hooks/useLiveOverlay.ts'
import { useSkyObjects } from '../hooks/useSkyObjects.ts'
import { useStatus } from '../hooks/useStatus.ts'
import { SkyHover } from '../components/SkyHover.tsx'
import { localApiClient } from '../services/client.ts'

export function LiveStream() {
  const { frame, status: streamStatus } = useFrameStream()
  const overlaySrc = useLiveOverlay(frame?.metadata)
  const { status } = useStatus()
  const sky = useSkyObjects(4.5)

  const [exposureUs, setExposureUs] = useState('')
  const [analogueGain, setAnalogueGain] = useState('')
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  async function toggleStreamMode() {
    if (!status) return
    setPending(true)
    setMessage(null)
    try {
      await localApiClient.setCameraMode(!status.stream_mode)
      setMessage(`Stream mode ${!status.stream_mode ? 'enabled' : 'disabled'}.`)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setPending(false)
    }
  }

  async function applyOverride() {
    setPending(true)
    setMessage(null)
    try {
      const body: { exposure_us?: number; analogue_gain?: number } = {}
      if (exposureUs.trim() !== '') body.exposure_us = Number(exposureUs)
      if (analogueGain.trim() !== '') body.analogue_gain = Number(analogueGain)
      if (body.exposure_us === undefined && body.analogue_gain === undefined) {
        setMessage('Enter an exposure and/or gain value first.')
        return
      }
      await localApiClient.setExposureOverride(body)
      setMessage('Manual override applied.')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setPending(false)
    }
  }

  async function clearOverride() {
    setPending(true)
    setMessage(null)
    try {
      await localApiClient.clearExposureOverride()
      setExposureUs('')
      setAnalogueGain('')
      setMessage('Manual override cleared — back to automatic exposure control.')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Live stream"
        actions={
          status ? (
            <StatusBadge tone={status.capturing ? 'live' : 'neutral'}>{status.capturing ? 'Capturing' : 'Idle'}</StatusBadge>
          ) : null
        }
      />

      <LiveFrame live={!!status?.capturing && !!frame}>
        {frame ? (
          <SkyHover objects={sky?.objects ?? []}>
            <ImageViewer src={frame.imageBlobUrl} overlaySrc={overlaySrc} alt="Live camera feed" />
          </SkyHover>
        ) : (
          <div className="flex aspect-video items-center justify-center text-sm text-ink-muted">
            {streamStatus === 'connecting' ? 'Connecting to live stream…' : 'Waiting for first frame…'}
          </div>
        )}
      </LiveFrame>

      {message ? <Message kind="info">{message}</Message> : null}

      <Panel title="Stream mode">
        <div className="flex items-center justify-between gap-4">
          <p className="text-sm text-ink-muted">
            Faster realtime preview cadence (day mode). Currently{' '}
            <span className="font-medium text-ink">{status?.stream_mode ? 'on' : 'off'}</span>.
          </p>
          <Button variant="primary" onClick={() => void toggleStreamMode()} disabled={pending || !status}>
            {status?.stream_mode ? 'Turn off' : 'Turn on'}
          </Button>
        </div>
      </Panel>

      <Panel title="Manual exposure override" actions={status?.manual_exposure_override ? <StatusBadge tone="live">Active</StatusBadge> : null}>
        <div className="flex flex-col gap-4">
          <p className="text-sm text-ink-muted">Overrides the automatic exposure controller until cleared.</p>
          <div className="flex flex-wrap items-end gap-4">
            <Field label="Exposure (µs)">
              <input
                type="number"
                min={0}
                value={exposureUs}
                onChange={(e) => setExposureUs(e.target.value)}
                placeholder={String(status?.exposure_us ?? '')}
                className={`${inputClass} w-36`}
              />
            </Field>
            <Field label="Analogue gain">
              <input
                type="number"
                min={0}
                step={0.1}
                value={analogueGain}
                onChange={(e) => setAnalogueGain(e.target.value)}
                placeholder={String(status?.analogue_gain ?? '')}
                className={`${inputClass} w-36`}
              />
            </Field>
            <Button variant="primary" onClick={() => void applyOverride()} disabled={pending}>
              Apply
            </Button>
            <Button variant="ghost" onClick={() => void clearOverride()} disabled={pending}>
              Clear override
            </Button>
          </div>
        </div>
      </Panel>
    </div>
  )
}

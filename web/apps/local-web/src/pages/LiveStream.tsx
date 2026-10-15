import { useState } from 'react'
import type { ReactNode } from 'react'
import { ImageViewer } from '@caelum/ui'
import { useFrameStream } from '../hooks/useFrameStream.ts'
import { useStatus } from '../hooks/useStatus.ts'
import { localApiClient } from '../services/client.ts'

export function LiveStream() {
  const { frame, status: streamStatus } = useFrameStream()
  const { status } = useStatus()

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
      <h1 className="text-sm font-semibold tracking-[0.2em] text-ink-dim uppercase">Live stream</h1>

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

      <Panel title="Stream mode">
        <div className="flex items-center justify-between gap-4">
          <p className="text-sm text-ink-dim">
            Faster realtime preview cadence (day mode). Currently{' '}
            <span className="font-medium text-ink">{status?.stream_mode ? 'on' : 'off'}</span>.
          </p>
          <Button onClick={() => void toggleStreamMode()} disabled={pending || !status}>
            {status?.stream_mode ? 'Turn off' : 'Turn on'}
          </Button>
        </div>
      </Panel>

      <Panel title="Manual exposure override">
        <p className="text-sm text-ink-dim">
          Overrides the automatic exposure controller until cleared.{' '}
          {status?.manual_exposure_override ? (
            <span className="font-medium text-amber-bright">Currently active.</span>
          ) : (
            <span className="text-ink-faint">Currently off.</span>
          )}
        </p>
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Exposure (µs)">
            <input
              type="number"
              min={0}
              value={exposureUs}
              onChange={(e) => setExposureUs(e.target.value)}
              placeholder={String(status?.exposure_us ?? '')}
              className="w-36 border border-line bg-void px-3 py-1.5 font-mono text-ink focus:border-amber focus:outline-none"
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
              className="w-36 border border-line bg-void px-3 py-1.5 font-mono text-ink focus:border-amber focus:outline-none"
            />
          </Field>
          <Button onClick={() => void applyOverride()} disabled={pending}>
            Apply
          </Button>
          <Button variant="ghost" onClick={() => void clearOverride()} disabled={pending}>
            Clear override
          </Button>
        </div>
        {message ? <p className="text-sm text-ink-dim">{message}</p> : null}
      </Panel>
    </div>
  )
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4 border border-line bg-panel p-4">
      <h2 className="text-xs font-semibold tracking-widest text-ink-faint uppercase">{title}</h2>
      {children}
    </section>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium tracking-wide text-ink-dim uppercase">
      {label}
      {children}
    </label>
  )
}

function Button({
  children,
  onClick,
  disabled,
  variant = 'primary',
}: {
  children: ReactNode
  onClick: () => void
  disabled?: boolean
  variant?: 'primary' | 'ghost'
}) {
  const base = 'px-4 py-2 text-xs font-semibold tracking-wide uppercase transition disabled:cursor-not-allowed disabled:opacity-40'
  const styles =
    variant === 'primary'
      ? 'bg-amber text-void hover:bg-amber-bright'
      : 'border border-line text-ink-dim hover:border-amber-dim hover:text-ink'
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={[base, styles].join(' ')}>
      {children}
    </button>
  )
}

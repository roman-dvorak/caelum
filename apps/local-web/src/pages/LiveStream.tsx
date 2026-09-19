import { useState } from 'react'
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
      <h1 className="text-lg font-semibold text-slate-100">Live stream</h1>

      <section className="overflow-hidden rounded-lg border border-slate-800 bg-black">
        {frame ? (
          <ImageViewer src={frame.imageBlobUrl} metadata={frame.metadata} alt="Live camera feed" />
        ) : (
          <div className="flex aspect-video items-center justify-center text-sm text-slate-500">
            {streamStatus === 'connecting' ? 'Connecting to live stream…' : 'Waiting for first frame…'}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-medium text-slate-100">Stream mode</h2>
            <p className="text-sm text-slate-500">
              Faster realtime preview cadence (day mode). Currently{' '}
              <span className="font-medium text-slate-300">{status?.stream_mode ? 'on' : 'off'}</span>.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void toggleStreamMode()}
            disabled={pending || !status}
            className="rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {status?.stream_mode ? 'Turn off' : 'Turn on'}
          </button>
        </div>
      </section>

      <section className="flex flex-col gap-4 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
        <div>
          <h2 className="font-medium text-slate-100">Manual exposure override</h2>
          <p className="text-sm text-slate-500">
            Overrides the automatic exposure controller until cleared.{' '}
            {status?.manual_exposure_override ? (
              <span className="font-medium text-amber-400">Currently active.</span>
            ) : (
              <span className="text-slate-500">Currently off.</span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-sm text-slate-300">
            Exposure (µs)
            <input
              type="number"
              min={0}
              value={exposureUs}
              onChange={(e) => setExposureUs(e.target.value)}
              placeholder={String(status?.exposure_us ?? '')}
              className="w-36 rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-sky-500 focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm text-slate-300">
            Analogue gain
            <input
              type="number"
              min={0}
              step={0.1}
              value={analogueGain}
              onChange={(e) => setAnalogueGain(e.target.value)}
              placeholder={String(status?.analogue_gain ?? '')}
              className="w-36 rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-sky-500 focus:outline-none"
            />
          </label>
          <button
            type="button"
            onClick={() => void applyOverride()}
            disabled={pending}
            className="rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Apply
          </button>
          <button
            type="button"
            onClick={() => void clearOverride()}
            disabled={pending}
            className="rounded-md border border-slate-700 px-4 py-2 text-sm font-medium text-slate-300 transition hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Clear override
          </button>
        </div>
        {message ? <p className="text-sm text-slate-400">{message}</p> : null}
      </section>
    </div>
  )
}

import { useCallback, useEffect, useState } from 'react'
import type { AppConfig, CameraOptions } from '@caelum/api-client'
import { Field, Message, Panel, Readout, inputClass } from '@caelum/ui'
import { localApiClient } from '../services/client.ts'

/**
 * Picking a camera as a menu rather than a guess at a device path.
 *
 * The backend reports which devices actually exist on the host and which
 * configuration the capture thread currently has *open* — the latter is the
 * point: a change to `config.camera` is a request, and it only becomes real
 * once the capture thread reopens the device on its next cycle. That gap is
 * where a wrong device path shows up, so the picker surfaces it instead of
 * reporting success the moment the config write returns.
 */
export function CameraPicker({ onConfigChange }: { onConfigChange: (config: AppConfig) => void }) {
  const [options, setOptions] = useState<CameraOptions | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [pollToken, setPollToken] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function run() {
      try {
        const next = await localApiClient.getCameraOptions()
        if (!cancelled) {
          setOptions(next)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [pollToken])

  // While a change is pending, poll until the capture thread has picked it
  // up — one cycle can be a minute at the daytime capture interval.
  useEffect(() => {
    if (!options || options.applied) return
    const id = window.setInterval(() => setPollToken((n) => n + 1), 2000)
    return () => window.clearInterval(id)
  }, [options])

  const apply = useCallback(
    async (patch: Record<string, unknown>) => {
      setBusy(true)
      setError(null)
      try {
        onConfigChange(await localApiClient.updateConfig({ camera: patch }))
        setPollToken((n) => n + 1)
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setBusy(false)
      }
    },
    [onConfigChange],
  )

  if (!options) {
    return error ? <Message kind="error">{error}</Message> : null
  }

  const { configured } = options

  return (
    <Panel
      title="Camera"
      actions={
        options.applied ? (
          <span className="border border-success/50 px-2 py-1 text-[0.65rem] tracking-[0.15em] text-success uppercase">
            Active
          </span>
        ) : (
          <span className="border border-amber-dim px-2 py-1 text-[0.65rem] tracking-[0.15em] text-amber uppercase">
            Applying…
          </span>
        )
      }
    >
      <div className="flex flex-col gap-4">
        {error ? <Message kind="error">{error}</Message> : null}

        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Backend"
            hint={
              configured.backend === 'opencv'
                ? 'Any UVC/V4L2 webcam.'
                : configured.backend === 'picamera2'
                  ? 'Raspberry Pi camera module.'
                  : 'Synthetic frames — no hardware needed.'
            }
          >
            <select
              className={inputClass}
              value={configured.backend}
              disabled={busy}
              onChange={(e) => void apply({ backend: e.target.value })}
            >
              {options.backends.map((backend) => (
                <option key={backend} value={backend}>
                  {backend}
                </option>
              ))}
            </select>
          </Field>

          <Field
            label="Device"
            hint={
              configured.backend === 'opencv'
                ? options.v4l2_devices.length > 0
                  ? 'Detected on this host.'
                  : 'No /dev/video* devices found — is the camera plugged in?'
                : 'Sensor identifier for this backend.'
            }
          >
            {configured.backend === 'opencv' && options.v4l2_devices.length > 0 ? (
              <select
                className={inputClass}
                value={configured.sensor_id}
                disabled={busy}
                onChange={(e) => void apply({ sensor_id: e.target.value })}
              >
                {/* The configured value may not be in the detected list (an
                    unplugged camera); keep it selectable so the UI does not
                    silently rewrite the config to a different device. */}
                {[...new Set([...options.v4l2_devices, configured.sensor_id])].map((device) => (
                  <option key={device} value={device}>
                    {device}
                  </option>
                ))}
              </select>
            ) : (
              <DeviceInput
                value={configured.sensor_id}
                disabled={busy}
                onCommit={(sensor_id) => void apply({ sensor_id })}
              />
            )}
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-3 border-t border-line-soft pt-3 sm:grid-cols-4">
          <Readout label="Open backend" value={options.active_backend_class} />
          <Readout label="Open device" value={options.active?.sensor_id ?? '—'} />
          <Readout
            label="Resolution"
            value={`${configured.resolution[0]}×${configured.resolution[1]}`}
          />
          <Readout label="State" value={options.applied ? 'applied' : 'pending'} />
        </div>

        {!options.applied ? (
          <p className="text-xs text-ink-faint">
            The capture thread reopens the camera between exposures, so a change takes up to one
            capture interval to appear. If it stays pending, the new device probably could not be
            opened — check the Terminal or the service log.
          </p>
        ) : null}
      </div>
    </Panel>
  )
}

/** Free-text device field that only commits on blur/Enter, so a config
 * write is not fired for every keystroke. */
function DeviceInput({
  value,
  disabled,
  onCommit,
}: {
  value: string
  disabled: boolean
  onCommit: (value: string) => void
}) {
  const [draft, setDraft] = useState(value)

  return (
    <input
      className={inputClass}
      value={draft}
      disabled={disabled}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => draft !== value && onCommit(draft)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
        if (e.key === 'Escape') setDraft(value)
      }}
    />
  )
}

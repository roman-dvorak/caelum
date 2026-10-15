import { useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { Button, Field, Message, PageHeader, Panel, inputClass } from '@caelum/ui'
import { useFrameStream } from '../hooks/useFrameStream.ts'
import { localApiClient } from '../services/client.ts'

interface FractionalRect {
  x: number
  y: number
  w: number
  h: number
}

const DEFAULT_PATCH: FractionalRect = { x: 0.4, y: 0.4, w: 0.2, h: 0.2 }

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/**
 * White balance service tool: a live preview with manual R/B gain sliders
 * (applied — and saved as the camera's default — as you drag) plus a
 * draggable patch selection that derives gains automatically from a
 * neutral gray/white surface in the frame.
 */
export function WhiteBalance() {
  const { frame, status: streamStatus } = useFrameStream()
  const [redGain, setRedGain] = useState(1.0)
  const [blueGain, setBlueGain] = useState(1.0)
  const [patch, setPatch] = useState<FractionalRect>(DEFAULT_PATCH)
  const [message, setMessage] = useState<string | null>(null)
  const [applying, setApplying] = useState(false)
  const [calibrating, setCalibrating] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const applyTimer = useRef<number | undefined>(undefined)

  function scheduleApply(nextRed: number, nextBlue: number) {
    if (applyTimer.current !== undefined) window.clearTimeout(applyTimer.current)
    applyTimer.current = window.setTimeout(() => {
      void applyGains(nextRed, nextBlue)
    }, 250)
  }

  async function applyGains(red: number, blue: number) {
    setApplying(true)
    setMessage(null)
    try {
      await localApiClient.setWhiteBalance({ red_gain: red, blue_gain: blue })
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setApplying(false)
    }
  }

  async function autoCalibrate() {
    setCalibrating(true)
    setMessage(null)
    try {
      const result = await localApiClient.autoCalibrateWhiteBalance(patch)
      setRedGain(result.red_gain)
      setBlueGain(result.blue_gain)
      setMessage('Calibrated and saved from the selected patch.')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setCalibrating(false)
    }
  }

  function startPatchDrag(startEvent: ReactPointerEvent, mode: 'move' | 'resize') {
    startEvent.stopPropagation()
    startEvent.preventDefault()
    const container = containerRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    const start = { ...patch }
    const startClientX = startEvent.clientX
    const startClientY = startEvent.clientY

    function onMove(moveEvent: PointerEvent) {
      const dx = (moveEvent.clientX - startClientX) / rect.width
      const dy = (moveEvent.clientY - startClientY) / rect.height
      if (mode === 'move') {
        setPatch({
          ...start,
          x: clamp(start.x + dx, 0, 1 - start.w),
          y: clamp(start.y + dy, 0, 1 - start.h),
        })
      } else {
        setPatch({
          ...start,
          w: clamp(start.w + dx, 0.02, 1 - start.x),
          h: clamp(start.h + dy, 0.02, 1 - start.y),
        })
      }
    }
    function onUp() {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  return (
    <>
      <PageHeader
        title="White balance"
        description="Adjust red/blue gain against the live preview, or drag the patch over a neutral gray/white surface and calibrate automatically. Every change is saved as the camera's default."
      />

      {message ? <Message kind="info">{message}</Message> : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <div ref={containerRef} className="relative overflow-hidden border border-line bg-void">
          {frame ? (
            <img src={frame.imageBlobUrl} alt="Live camera feed" className="block w-full" />
          ) : (
            <div className="flex aspect-video items-center justify-center text-sm text-ink-faint">
              {streamStatus === 'connecting' ? 'Connecting to live stream…' : 'Waiting for first frame…'}
            </div>
          )}

          <div
            onPointerDown={(e) => startPatchDrag(e, 'move')}
            className="absolute cursor-move border-2 border-amber bg-amber/10"
            style={{
              left: `${patch.x * 100}%`,
              top: `${patch.y * 100}%`,
              width: `${patch.w * 100}%`,
              height: `${patch.h * 100}%`,
            }}
          >
            <div
              onPointerDown={(e) => startPatchDrag(e, 'resize')}
              className="absolute -right-1.5 -bottom-1.5 h-3 w-3 cursor-nwse-resize border border-void bg-amber"
            />
          </div>
        </div>

        <div className="flex flex-col gap-3">
          <Panel title="Manual gains">
            <div className="flex flex-col gap-3">
              <Field label={`Red gain (${redGain.toFixed(2)})`}>
                <input
                  type="range"
                  min={0.1}
                  max={8}
                  step={0.05}
                  value={redGain}
                  onChange={(e) => {
                    const next = Number(e.target.value)
                    setRedGain(next)
                    scheduleApply(next, blueGain)
                  }}
                />
              </Field>
              <Field label={`Blue gain (${blueGain.toFixed(2)})`}>
                <input
                  type="range"
                  min={0.1}
                  max={8}
                  step={0.05}
                  value={blueGain}
                  onChange={(e) => {
                    const next = Number(e.target.value)
                    setBlueGain(next)
                    scheduleApply(redGain, next)
                  }}
                />
              </Field>
              <p className="text-xs text-ink-faint">{applying ? 'Applying…' : 'Applied as you drag.'}</p>
            </div>
          </Panel>

          <Panel title="Auto-calibrate">
            <div className="flex flex-col gap-2">
              <p className="text-xs text-ink-faint">
                Drag the amber box over a neutral gray/white surface in the preview, then calibrate.
              </p>
              <Field label="Patch">
                <input
                  className={inputClass}
                  readOnly
                  value={`x=${patch.x.toFixed(2)} y=${patch.y.toFixed(2)} w=${patch.w.toFixed(2)} h=${patch.h.toFixed(2)}`}
                />
              </Field>
              <Button variant="primary" onClick={() => void autoCalibrate()} disabled={calibrating}>
                Calibrate from patch
              </Button>
            </div>
          </Panel>
        </div>
      </div>
    </>
  )
}

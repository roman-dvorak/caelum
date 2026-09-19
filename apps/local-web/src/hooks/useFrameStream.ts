import { useEffect, useRef, useState } from 'react'
import { connectFrameStream, type StreamFrame } from '@caelum/api-client'

const RECONNECT_DELAY_MS = 2_000

export type FrameStreamStatus = 'connecting' | 'open' | 'closed'

export interface UseFrameStreamResult {
  frame: StreamFrame | null
  status: FrameStreamStatus
}

/** Subscribes to `/ws/stream` for the lifetime of the component, reconnecting
 * automatically (with a fixed backoff) if the connection drops — the kind of
 * thing you want on a page left open for hours pointed at a Pi. */
export function useFrameStream(): UseFrameStreamResult {
  const [frame, setFrame] = useState<StreamFrame | null>(null)
  const [status, setStatus] = useState<FrameStreamStatus>('connecting')
  const reconnectTimer = useRef<number | undefined>(undefined)

  useEffect(() => {
    let disposed = false
    let handle: ReturnType<typeof connectFrameStream> | null = null

    function connect() {
      if (disposed) return
      setStatus('connecting')
      handle = connectFrameStream({
        onOpen: () => {
          if (!disposed) setStatus('open')
        },
        onFrame: (next) => {
          if (!disposed) setFrame(next)
        },
        onClose: () => {
          if (disposed) return
          setStatus('closed')
          reconnectTimer.current = window.setTimeout(connect, RECONNECT_DELAY_MS)
        },
      })
    }

    connect()

    return () => {
      disposed = true
      if (reconnectTimer.current !== undefined) window.clearTimeout(reconnectTimer.current)
      handle?.close()
    }
  }, [])

  return { frame, status }
}

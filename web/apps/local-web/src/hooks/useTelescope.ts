import { useEffect, useState } from 'react'
import type { MountState } from '@caelum/api-client'
import type { TelescopePointing } from '@roman-dvorak/caelum-sky'
import { localApiClient } from '../services/client.ts'

const POLL_MS = 1500

/** The telescope's pointing for the sky canvas, refreshed every second or two —
 * independent of frames, so the crosshair follows a slew between them. Null
 * while the plugin is off or nothing has been reported. */
export function useTelescope(active: boolean): TelescopePointing | null {
  const [state, setState] = useState<MountState | null>(null)
  useEffect(() => {
    if (!active) return
    let disposed = false
    async function load() {
      try {
        const next = await localApiClient.getMountState()
        if (!disposed) setState(next)
      } catch {
        if (!disposed) setState(null)
      }
    }
    void load()
    const timer = window.setInterval(() => void load(), POLL_MS)
    return () => {
      disposed = true
      window.clearInterval(timer)
    }
  }, [active])

  if (!active || !state?.enabled || !state.status) return null
  return {
    status: state.status,
    raDeg: state.ra_deg ?? undefined,
    decDeg: state.dec_deg ?? undefined,
    epoch: state.epoch,
    altDeg: state.alt_deg ?? undefined,
    azDeg: state.az_deg ?? undefined,
    label: state.label,
  }
}

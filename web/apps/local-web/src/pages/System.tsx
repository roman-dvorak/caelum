import { useState } from 'react'
import type { NetworkInterfaceInfo } from '@caelum/api-client'
import { Button, Message, PageHeader, Panel, PowerIcon, Readout, StatusTile, formatBytes } from '@caelum/ui'
import { useSystemInfo } from '../hooks/useSystemInfo.ts'
import { localApiClient } from '../services/client.ts'
import { SoftwareUpdate } from '../components/SoftwareUpdate.tsx'

/**
 * Host machine vitals — CPU/RAM/disk/temperature/network — plus the two
 * actions no other page can offer: shutting down or rebooting the box this
 * software is running on. There is deliberately no "confirm and wait for it
 * to come back" flow here: the connection simply drops, same as unplugging
 * it, which is the honest thing to show for an action that ends the process
 * serving this very page.
 */
export function System() {
  const { info, error } = useSystemInfo()
  const [actionError, setActionError] = useState<string | null>(null)
  const [pending, setPending] = useState<'shutdown' | 'reboot' | null>(null)

  async function runAction(kind: 'shutdown' | 'reboot') {
    const verb = kind === 'shutdown' ? 'shut down' : 'reboot'
    if (!window.confirm(`${verb.charAt(0).toUpperCase()}${verb.slice(1)} this camera's host now? The capture and web UI will go offline.`)) {
      return
    }
    setPending(kind)
    setActionError(null)
    try {
      if (kind === 'shutdown') await localApiClient.shutdownSystem()
      else await localApiClient.rebootSystem()
      // A success response means the command was accepted; the process
      // (including this request) is about to die, so there is nothing
      // further to do here beyond leaving `pending` set for the UI hint.
    } catch (err) {
      setPending(null)
      setActionError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <>
      <PageHeader
        title="System"
        description="The host machine this camera software is running on."
        actions={
          <>
            <Button variant="danger" icon={<PowerIcon size={14} />} disabled={!!pending} onClick={() => void runAction('reboot')}>
              Reboot
            </Button>
            <Button variant="danger" icon={<PowerIcon size={14} />} disabled={!!pending} onClick={() => void runAction('shutdown')}>
              Shut down
            </Button>
          </>
        }
      />

      {error ? <Message kind="error">{error}</Message> : null}
      {actionError ? <Message kind="error">{actionError}</Message> : null}
      {pending ? (
        <Message kind="info">
          {pending === 'shutdown' ? 'Shutting down' : 'Rebooting'} — this page will stop responding shortly.
        </Message>
      ) : null}

      {!info ? null : (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-px bg-line-soft sm:grid-cols-3 lg:grid-cols-4">
            <StatusTile label="caelum" value={info.version} />
            <StatusTile label="Hostname" value={info.hostname} />
            <StatusTile label="Uptime" value={formatUptime(info.uptime_s)} />
            <StatusTile label="CPU" value={info.cpu_percent.toFixed(0)} unit="%" />
            <StatusTile label="CPU cores" value={String(info.cpu_count)} />
            <StatusTile
              label="Load avg (1/5/15m)"
              value={info.load_avg ? info.load_avg.map((v) => v.toFixed(2)).join(' / ') : '—'}
            />
            <StatusTile
              label="Memory"
              value={info.mem_percent.toFixed(0)}
              unit="%"
              hint={`${formatBytes(info.mem_used_bytes)} / ${formatBytes(info.mem_total_bytes)}`}
            />
          </div>

          {Object.keys(info.temperatures_c).length > 0 ? (
            <Panel title="Temperatures">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {Object.entries(info.temperatures_c).map(([label, celsius]) => (
                  <Readout key={label} label={label} value={`${celsius.toFixed(1)} °C`} />
                ))}
              </div>
            </Panel>
          ) : null}

          <Panel title="Storage">
            <div className="flex flex-col gap-3">
              {info.disks.map((disk) => (
                <div key={disk.path} className="flex flex-col gap-1">
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="font-mono text-ink-dim">{disk.path}</span>
                    <span className="text-ink-faint">
                      {formatBytes(disk.used_bytes)} / {formatBytes(disk.total_bytes)} ({disk.percent.toFixed(0)}%)
                    </span>
                  </div>
                  <div className="h-1.5 w-full bg-line-soft">
                    <div
                      className={`h-full ${disk.percent >= 90 ? 'bg-danger' : 'bg-amber'}`}
                      style={{ width: `${Math.min(100, disk.percent)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Network interfaces">
            <NetworkTable interfaces={info.network} />
          </Panel>

          <SoftwareUpdate runningVersion={info.version} />
        </div>
      )}
    </>
  )
}

function NetworkTable({ interfaces }: { interfaces: NetworkInterfaceInfo[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="text-xs tracking-wide text-ink-faint uppercase">
            <th className="pb-2 pr-4">Interface</th>
            <th className="pb-2 pr-4">Status</th>
            <th className="pb-2 pr-4">Speed</th>
            <th className="pb-2">Addresses</th>
          </tr>
        </thead>
        <tbody>
          {interfaces.map((iface) => (
            <tr key={iface.name} className="border-t border-line-soft">
              <td className="py-1.5 pr-4 font-mono text-ink">{iface.name}</td>
              <td className="py-1.5 pr-4">
                <span className={iface.is_up ? 'text-success' : 'text-ink-faint'}>
                  {iface.is_up ? 'Up' : 'Down'}
                </span>
              </td>
              <td className="py-1.5 pr-4 text-ink-dim">{iface.speed_mbps ? `${iface.speed_mbps} Mbps` : '—'}</td>
              <td className="py-1.5 font-mono text-xs text-ink-dim">
                {iface.addresses.length ? iface.addresses.join(', ') : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

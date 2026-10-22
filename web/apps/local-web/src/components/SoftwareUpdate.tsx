import { useEffect, useState } from 'react'
import { connectUpdateLog, type LogEntry, type UpdateStatusResponse } from '@caelum/api-client'
import { Button, DownloadIcon, Message, Panel, Readout, RefreshIcon } from '@caelum/ui'
import { localApiClient } from '../services/client.ts'

const BUSY_STATES = new Set(['downloading', 'installing', 'restarting'])
const POLL_INTERVAL_MS = 3_000

/**
 * Software update for a managed install (see caelum/update/). The backend
 * installs the new release next to the running one, switches over and
 * restarts; this panel streams the install log, then waits for the server
 * to come back with a different version. If the new release never comes up
 * healthy, the boot guard restores the old one, and `last_result` says so.
 */
export function SoftwareUpdate({ runningVersion }: { runningVersion: string | undefined }) {
  const [status, setStatus] = useState<UpdateStatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [working, setWorking] = useState(false)
  const [log, setLog] = useState<LogEntry[]>([])
  const [showLog, setShowLog] = useState(false)
  // The version an update was started from.
  const [startedFrom, setStartedFrom] = useState<string | null>(null)

  // Polled like the rest of the System page: the job runs server-side for
  // minutes and the server restarts underneath us, so push would buy little.
  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const next = await localApiClient.getUpdateStatus()
        if (!cancelled) setStatus(next)
      } catch {
        // Expected while the server restarts; the next poll catches up.
      }
    }
    void poll()
    const id = window.setInterval(() => void poll(), POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  const busy = !!status && BUSY_STATES.has(status.job_state)
  // Between starting an update and the server answering with another version
  // (or the same one with the update failed or rolled back).
  const restarting =
    startedFrom !== null &&
    runningVersion === startedFrom &&
    !busy &&
    status?.job_state !== 'failed' &&
    status?.last_result?.state !== 'rolled_back'
  const confirming = status?.last_result?.state === 'pending'

  useEffect(() => {
    if (!showLog) return
    const handle = connectUpdateLog({
      onBacklog: (entries) => setLog(entries),
      onEntry: (entry) => setLog((prev) => [...prev.slice(-2000), entry]),
    })
    return () => handle.close()
  }, [showLog])

  async function run(action: () => Promise<UpdateStatusResponse>, startsUpdate: boolean) {
    setWorking(true)
    setError(null)
    try {
      const next = await action()
      setStatus(next)
      if (startsUpdate) {
        setStartedFrom(next.current_version)
        setShowLog(true)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setWorking(false)
    }
  }

  function onUpload(file: File | undefined) {
    if (!file) return
    if (!window.confirm(`Install ${file.name}? caelum will restart.`)) return
    void run(() => localApiClient.uploadUpdate(file), true)
  }

  if (!status) return null

  const available = status.available
  const result = status.last_result

  return (
    <Panel
      title="Software update"
      actions={
        status.managed ? (
          <Button icon={<RefreshIcon size={14} />} disabled={working || busy} onClick={() => void run(() => localApiClient.checkUpdate(), false)}>
            Check for updates
          </Button>
        ) : null
      }
    >
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Readout label="Running version" value={<span className="font-mono">{status.current_version}</span>} />
          {status.managed ? (
            <Readout
              label="Available"
              value={available ? <span className="font-mono">{available.version}</span> : status.checked_at ? 'Up to date' : '—'}
            />
          ) : null}
        </div>

        {!status.managed ? (
          <p className="text-sm text-ink-muted">
            This is not a managed install (made by install-system.sh), so it is updated by hand, not from here.
          </p>
        ) : null}

        {error ? <Message kind="error">{error}</Message> : null}
        {status.check_error ? <Message kind="error">Update check failed: {status.check_error}</Message> : null}
        {status.job_state === 'failed' && status.job_error ? (
          <Message kind="error">
            Update to {status.job_target} failed: {status.job_error}. The running version was not touched.
          </Message>
        ) : null}
        {busy ? (
          <Message kind="info">
            {status.job_state === 'restarting' ? 'Restarting into' : 'Installing'} {status.job_target}… the camera keeps
            running until the switch.
          </Message>
        ) : restarting ? (
          <Message kind="info">Waiting for caelum to come back…</Message>
        ) : null}
        {!busy && !restarting && result?.state === 'rolled_back' ? (
          <Message kind="error">
            {result.to} did not start properly and was rolled back to {result.from} ({formatTime(result.at)}).
          </Message>
        ) : null}
        {!busy && !restarting && confirming ? (
          <Message kind="info">Running {result?.to}; confirming it stays up before removing old releases…</Message>
        ) : null}
        {!busy && !restarting && result?.state === 'success' && result.to === status.current_version ? (
          <Message kind="success">
            Updated from {result.from} to {result.to} ({formatTime(result.at)}).
          </Message>
        ) : null}

        {status.managed && available && !busy && !restarting ? (
          <div className="flex flex-col gap-2 border border-border-subtle p-3 rounded-md">
            {available.notes ? <p className="text-sm whitespace-pre-line text-ink-muted">{available.notes}</p> : null}
            <div>
              <Button
                variant="primary"
                icon={<DownloadIcon size={14} />}
                disabled={working}
                onClick={() => {
                  if (window.confirm(`Update to ${available.version}? caelum will restart; capture pauses for a minute.`)) {
                    void run(() => localApiClient.startUpdate(available.version), true)
                  }
                }}
              >
                Update to {available.version}
              </Button>
            </div>
          </div>
        ) : null}

        {status.managed ? (
          <div className="flex flex-wrap items-center gap-3 text-sm text-ink-muted">
            <label className="flex items-center gap-2">
              Install a wheel file:
              <input
                type="file"
                accept=".whl"
                disabled={working || busy || restarting}
                onChange={(e) => {
                  onUpload(e.target.files?.[0])
                  e.target.value = ''
                }}
              />
            </label>
            <button type="button" className="text-xs text-ink-muted underline" onClick={() => setShowLog((v) => !v)}>
              {showLog ? 'Hide install log' : 'Show install log'}
            </button>
          </div>
        ) : null}

        {showLog ? (
          <pre className="h-64 overflow-y-auto border border-border bg-surface-0 p-3 font-mono text-xs text-ink-muted rounded-sm">
            {log.length ? log.map((e) => e.message).join('\n') : 'No update has run since caelum started.'}
          </pre>
        ) : null}

        {status.managed ? (
          <p className="text-xs text-ink-muted">
            Releases from <span className="font-mono">{status.manifest_url}</span> (Settings → update.manifest_url).
          </p>
        ) : null}
      </div>
    </Panel>
  )
}

function formatTime(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

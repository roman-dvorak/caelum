import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  CaptureProgramCheckReport,
  CaptureProgramInfo,
  CaptureProgramSource,
  CaptureProgramTestRun,
  CaptureProgramsResponse,
} from '@caelum/api-client'
import {
  Button,
  DownloadIcon,
  EmptyState,
  Field,
  Loading,
  Message,
  PageHeader,
  Panel,
  PlayIcon,
  RefreshIcon,
  StatusBadge,
  TrashIcon,
  buttonClass,
  inputClass,
} from '@caelum/ui'
import { localApiClient } from '../services/client.ts'

const POLL_MS = 2000

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

function stem(name: string): string {
  return name.replace(/\.py$/, '')
}

/** A program's module docstring — the built-ins document their params there. */
function docstring(source: string): string | null {
  const match = /^\s*(?:"""([\s\S]*?)"""|'''([\s\S]*?)''')/.exec(source)
  return match ? (match[1] ?? match[2]).trim() : null
}

function formatExposure(us: number): string {
  if (us >= 1_000_000) return `${(us / 1_000_000).toFixed(2)} s`
  if (us >= 1_000) return `${(us / 1_000).toFixed(1)} ms`
  return `${us} µs`
}

const NEW_PROGRAM = `"""What this program does, and its params (\`capture.params.<name>\`)."""

PROGRAM = {"description": "My capture program", "kind": "single"}


async def capture(ctx):
    frame = await ctx.capture(exposure_us=ctx.commanded.exposure_us, analogue_gain=ctx.commanded.analogue_gain)
    return frame
`

/**
 * Capture programs: which one runs each slot (default, HDR, fixed, darks or
 * a user's own), its parameters, and Check / Test once / Activate — a test
 * run takes real frames once, outside production, and shows them here.
 */
export function CapturePrograms() {
  const [data, setData] = useState<CaptureProgramsResponse | null>(null)
  const [params, setParams] = useState<Record<string, Record<string, unknown>>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const uploadRef = useRef<HTMLInputElement>(null)

  const reload = useCallback(async () => {
    try {
      const [list, config] = await Promise.all([localApiClient.listCapturePrograms(), localApiClient.getConfig()])
      setData(list)
      setParams(config.capture?.params ?? {})
      setSelected((current) => current ?? list.active.name)
      setError(null)
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const tick = () => {
      if (!cancelled) void reload()
    }
    tick()
    const id = window.setInterval(tick, 5000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [reload])

  async function createProgram() {
    const name = window.prompt('Name of the new program (lower-case, ending in .py):', 'my_program.py')
    if (!name) return
    try {
      await localApiClient.saveCaptureProgram(name.trim(), NEW_PROGRAM)
      await reload()
      setSelected(name.trim())
    } catch (err) {
      setError(errorText(err))
    }
  }

  async function upload(file: File | undefined) {
    if (!file) return
    try {
      const saved = await localApiClient.uploadCaptureProgram(file)
      await reload()
      setSelected(saved.name)
      setNotice(`Uploaded ${saved.name}. Check and test it before activating.`)
    } catch (err) {
      setError(errorText(err))
    }
  }

  if (!data) return error ? <Message kind="error">{error}</Message> : <Loading label="Loading capture programs…" />

  const { status, active } = data
  const info = data.programs.find((p) => p.name === selected) ?? null

  return (
    <>
      <PageHeader
        title="Capture programs"
        description="What the camera captures each slot. Save, check and test a program, then activate it — production changes only on activation."
        actions={
          <StatusBadge tone={status.fallback_active ? 'error' : 'live'}>
            Running {status.name ?? '—'}
          </StatusBadge>
        }
      />

      <div className="flex flex-col gap-4">
        {error ? <Message kind="error">{error}</Message> : null}
        {notice ? <Message kind="info">{notice}</Message> : null}
        {status.fallback_active ? (
          <Message kind="warning">
            {status.fallback_for?.join(', ') ?? active.name} failed and was replaced by the built-in default.py
            {status.last_error ? `: ${status.last_error}` : ''}. Activate a working version to switch back.
          </Message>
        ) : null}
        {!data.editing_enabled ? (
          <Message kind="info">
            Editing is turned off (capture.editing_enabled): programs can be viewed, not saved, tested or activated.
          </Message>
        ) : null}

        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
          <Panel
            title="Programs"
            bodyClassName="p-2"
            actions={
              data.editing_enabled ? (
                <>
                  <Button variant="ghost" className="px-2" onClick={() => void createProgram()}>
                    New
                  </Button>
                  <Button variant="ghost" className="px-2" onClick={() => uploadRef.current?.click()}>
                    Upload
                  </Button>
                  <input
                    ref={uploadRef}
                    type="file"
                    accept=".py"
                    className="hidden"
                    onChange={(e) => {
                      void upload(e.target.files?.[0])
                      e.target.value = ''
                    }}
                  />
                </>
              ) : null
            }
          >
            <div className="flex flex-col gap-1">
              {data.programs.map((program) => (
                <ProgramListItem
                  key={program.name}
                  program={program}
                  active={program.name === active.name}
                  selected={program.name === selected}
                  onSelect={() => {
                    setSelected(program.name)
                    setNotice(null)
                  }}
                />
              ))}
            </div>
            <p className="px-2 pt-3 pb-1 text-xs text-ink-muted">
              User programs live in <span className="font-mono text-code-sm break-all">{data.directory}</span>
            </p>
          </Panel>

          {info ? (
            <ProgramDetail
              key={info.name}
              info={info}
              isActive={info.name === active.name}
              activeSha={active.sha256}
              data={data}
              params={params[stem(info.name)] ?? {}}
              onChanged={reload}
              onDeleted={() => {
                setSelected(active.name)
                void reload()
              }}
              onDuplicated={setSelected}
            />
          ) : (
            <EmptyState>Select a program.</EmptyState>
          )}
        </div>
      </div>
    </>
  )
}

function ProgramListItem({
  program,
  active,
  selected,
  onSelect,
}: {
  program: CaptureProgramInfo
  active: boolean
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={[
        'flex flex-col gap-1 rounded-md px-3 py-2.5 text-left transition',
        selected ? 'bg-sky-surface ring-1 ring-sky/40' : 'hover:bg-surface-400/40',
      ].join(' ')}
    >
      <span className="flex items-center justify-between gap-2">
        <span className="font-mono text-code-md text-ink">{program.name}</span>
        {active ? <StatusBadge tone="live">Active</StatusBadge> : null}
      </span>
      {program.description ? <span className="text-xs text-ink-muted">{program.description}</span> : null}
      <span className="flex gap-1.5">
        <StatusBadge>{program.origin === 'builtin' ? 'Built-in' : 'User'}</StatusBadge>
        {program.kind ? <StatusBadge>{program.kind}</StatusBadge> : null}
      </span>
    </button>
  )
}

function ProgramDetail({
  info,
  isActive,
  activeSha,
  data,
  params,
  onChanged,
  onDeleted,
  onDuplicated,
}: {
  info: CaptureProgramInfo
  isActive: boolean
  activeSha: string | null
  data: CaptureProgramsResponse
  params: Record<string, unknown>
  onChanged: () => Promise<void>
  onDeleted: () => void
  onDuplicated: (name: string) => void
}) {
  const [program, setProgram] = useState<CaptureProgramSource | null>(null)
  const [draft, setDraft] = useState('')
  const [paramsText, setParamsText] = useState(() => JSON.stringify(params, null, 2))
  const [check, setCheck] = useState<CaptureProgramCheckReport | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [runs, setRuns] = useState<CaptureProgramTestRun[]>([])
  const [openRun, setOpenRun] = useState<string | null>(null)

  const editable = data.editing_enabled
  const isUser = info.origin === 'user'
  const dirty = program !== null && draft !== program.source

  useEffect(() => {
    let cancelled = false
    localApiClient.getCaptureProgram(info.name).then(
      (next) => {
        if (cancelled) return
        setProgram(next)
        setDraft(next.source)
      },
      (err: unknown) => !cancelled && setError(errorText(err)),
    )
    return () => {
      cancelled = true
    }
  }, [info.name])

  const loadRuns = useCallback(async () => {
    const list = await localApiClient.listCaptureProgramTestRuns(info.name)
    setRuns(list.runs)
    setOpenRun((current) => current ?? list.runs[0]?.run_id ?? null)
  }, [info.name])

  // Keep polling while a test of this program is queued or running.
  const inFlight = runs.some((r) => r.status === 'queued' || r.status === 'running')
  useEffect(() => {
    let cancelled = false
    const tick = () => {
      loadRuns().catch((err: unknown) => !cancelled && setError(errorText(err)))
    }
    tick()
    if (!inFlight) return () => void (cancelled = true)
    const id = window.setInterval(tick, POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [loadRuns, inFlight])

  async function act(label: string, action: () => Promise<void>) {
    setBusy(label)
    setError(null)
    setMessage(null)
    try {
      await action()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(null)
    }
  }

  const save = () =>
    act('save', async () => {
      const saved = await localApiClient.saveCaptureProgram(info.name, draft)
      setProgram((p) => (p ? { ...p, source: draft, sha256: saved.sha256 } : p))
      setMessage('Saved. Production still runs the activated version until you activate this one.')
      await onChanged()
    })

  const runCheck = () =>
    act('check', async () => {
      setCheck(await localApiClient.checkCaptureProgram(info.name, draft))
    })

  const runTest = () =>
    act('test', async () => {
      if (dirty) throw new Error('Save the program first — a test runs the saved version.')
      const queued = await localApiClient.testCaptureProgram(info.name)
      setOpenRun(queued.run_id)
      await loadRuns()
    })

  const activate = () =>
    act('activate', async () => {
      if (dirty) throw new Error('Save the program first — activation takes the saved version.')
      if (!program) return
      if (!window.confirm(`Activate ${info.name}? It runs from the next capture slot on.`)) return
      const report = await localApiClient.checkCaptureProgram(info.name, program.source)
      setCheck(report)
      if (!report.ok) throw new Error('Check failed — see the report below. Nothing was changed.')
      await localApiClient.activateCaptureProgram(info.name, program.sha256)
      setMessage(`${info.name} is active from the next slot.`)
      await onChanged()
    })

  const remove = () =>
    act('delete', async () => {
      if (!window.confirm(`Delete ${info.name}? Its archived versions stay.`)) return
      await localApiClient.deleteCaptureProgram(info.name)
      onDeleted()
    })

  const duplicate = () =>
    act('duplicate', async () => {
      const suggested = `${stem(info.name)}_copy.py`
      const name = window.prompt('Name of the copy (lower-case, ending in .py):', suggested)?.trim()
      if (!name) return
      await localApiClient.saveCaptureProgram(name, draft)
      await onChanged()
      onDuplicated(name)
    })

  const saveParams = () =>
    act('params', async () => {
      let parsed: Record<string, unknown>
      try {
        parsed = JSON.parse(paramsText) as Record<string, unknown>
      } catch {
        throw new Error('Parameters are not valid JSON.')
      }
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Parameters must be a JSON object.')
      }
      await localApiClient.updateConfig({ capture: { params: { [stem(info.name)]: parsed } } })
      setMessage('Parameters saved — used from the next slot (and by Check and Test).')
      await onChanged()
    })

  const testBusy = !!(data.status.pending_test || data.status.running_test)
  const activeUpToDate = isActive && (info.origin === 'builtin' || activeSha === program?.sha256)
  const doc = program ? docstring(program.source) : null

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <Panel
        title={<span className="font-mono">{info.name}</span>}
        actions={isActive ? <StatusBadge tone="live">Active</StatusBadge> : null}
      >
        <div className="flex flex-col gap-4">
          {info.description ? <p className="text-sm text-ink">{info.description}</p> : null}
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void runCheck()} disabled={!editable || !program || busy !== null}>
              {busy === 'check' ? 'Checking…' : 'Check'}
            </Button>
            <Button
              icon={<PlayIcon size={16} />}
              onClick={() => void runTest()}
              disabled={!editable || !program || busy !== null || testBusy}
              title={testBusy ? 'Another test is queued or running' : 'Run once on the camera, outside production'}
            >
              {busy === 'test' ? 'Queuing…' : 'Test once'}
            </Button>
            <Button
              variant="primary"
              onClick={() => void activate()}
              disabled={!editable || !program || busy !== null || activeUpToDate}
            >
              {activeUpToDate ? 'Active' : busy === 'activate' ? 'Activating…' : 'Activate'}
            </Button>
            <Button onClick={() => void duplicate()} disabled={!editable || !program || busy !== null}>
              Duplicate
            </Button>
            {isUser ? (
              <Button
                variant="error"
                icon={<TrashIcon size={16} />}
                onClick={() => void remove()}
                disabled={!editable || isActive || busy !== null}
                title={isActive ? 'Activate another program first' : undefined}
              >
                Delete
              </Button>
            ) : null}
          </div>
          {error ? <Message kind="error">{error}</Message> : null}
          {message ? <Message kind="success">{message}</Message> : null}
          <p className="font-mono text-code-sm text-ink-muted">
            {info.origin === 'builtin' ? 'built-in' : 'user'} · sha256 {program?.sha256.slice(0, 12) ?? '…'}
            {isActive && activeSha && program && activeSha !== program.sha256 ? ' · edited since activation' : ''}
          </p>
        </div>
      </Panel>

      {check ? <CheckReport report={check} /> : null}

      <TestRuns runs={runs} openRun={openRun} onOpen={setOpenRun} onRefresh={() => void loadRuns()} />

      <Panel title="Parameters">
        <div className="flex flex-col gap-3">
          {doc ? (
            <pre className="overflow-x-auto rounded-sm border border-border-subtle bg-surface-0 p-3 font-mono text-code-sm whitespace-pre-wrap text-ink-muted">
              {doc}
            </pre>
          ) : null}
          <Field label={`capture.params.${stem(info.name)}`} hint="A JSON object; the program reads it as ctx.params.">
            <textarea
              value={paramsText}
              onChange={(e) => setParamsText(e.target.value)}
              rows={Math.min(12, Math.max(3, paramsText.split('\n').length))}
              spellCheck={false}
              className={`${inputClass} text-code-sm`}
            />
          </Field>
          <div>
            <Button onClick={() => void saveParams()} disabled={busy !== null}>
              Save parameters
            </Button>
          </div>
        </div>
      </Panel>

      <Panel
        title="Source"
        actions={
          isUser && editable ? (
            <Button variant="primary" onClick={() => void save()} disabled={!dirty || busy !== null}>
              {busy === 'save' ? 'Saving…' : 'Save'}
            </Button>
          ) : null
        }
      >
        {!program ? (
          <Loading />
        ) : isUser && editable ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={Math.min(40, Math.max(12, draft.split('\n').length + 1))}
            spellCheck={false}
            className={`${inputClass} text-code-sm leading-relaxed`}
          />
        ) : (
          <pre className="max-h-[32rem] overflow-auto rounded-sm border border-border-subtle bg-surface-0 p-3 font-mono text-code-sm text-ink">
            {program.source}
          </pre>
        )}
        {program && info.origin === 'builtin' ? (
          <p className="mt-2 text-xs text-ink-muted">
            Built-in programs can't be edited — Duplicate makes an editable copy.
          </p>
        ) : null}
      </Panel>
    </div>
  )
}

const ISSUE_TONES = { error: 'error', warning: 'warning', info: 'info' } as const

function CheckReport({ report }: { report: CaptureProgramCheckReport }) {
  const runs = report.simulation?.runs ?? []
  return (
    <Panel
      title="Check"
      actions={<StatusBadge tone={report.ok ? 'success' : 'error'}>{report.ok ? 'Passed' : 'Failed'}</StatusBadge>}
    >
      <div className="flex flex-col gap-3">
        {report.issues.length === 0 ? (
          <p className="text-sm text-ink-muted">No issues.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {report.issues.map((issue, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <StatusBadge tone={ISSUE_TONES[issue.level]}>{issue.level}</StatusBadge>
                <span className="text-ink">
                  {issue.line ? <span className="font-mono text-ink-muted">line {issue.line}: </span> : null}
                  {issue.message}
                </span>
              </li>
            ))}
          </ul>
        )}
        {runs.length ? (
          <div className="overflow-x-auto">
            <p className="mb-1.5 text-xs text-ink-muted">
              Simulated against the camera's limits ({report.simulation?.period}):
            </p>
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-label-sm tracking-[0.08em] text-ink-muted uppercase">
                  <th className="pr-4 pb-2">Run</th>
                  <th className="pr-4 pb-2">Captures</th>
                  <th className="pr-4 pb-2">Returned</th>
                  <th className="pb-2">Frames: exposure · brightness</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.slot} className="border-t border-border-subtle align-top">
                    <td className="py-1.5 pr-4 font-mono">{run.slot}</td>
                    <td className="py-1.5 pr-4 font-mono">{run.captures ?? '—'}</td>
                    <td className="py-1.5 pr-4">
                      {run.error ? (
                        <span className="text-error">{run.error.type}</span>
                      ) : run.returned ? (
                        `${run.returned.kind} × ${run.returned.count}`
                      ) : (
                        'nothing'
                      )}
                    </td>
                    <td className="py-1.5 font-mono text-code-sm text-ink-muted">
                      {run.returned?.frames.length
                        ? run.returned.frames.map((f) => {
                            const exposure = Number(f.requested?.exposure_us ?? NaN)
                            return (
                              <div key={f.index} className="whitespace-nowrap">
                                {Number.isFinite(exposure) ? formatExposure(exposure) : '?'} · {f.brightness_median}
                              </div>
                            )
                          })
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {report.simulation?.log.length ? <LogBlock lines={report.simulation.log} /> : null}
      </div>
    </Panel>
  )
}

const RUN_TONES = { queued: 'neutral', running: 'live', done: 'success', error: 'error', stopped: 'warning' } as const

function TestRuns({
  runs,
  openRun,
  onOpen,
  onRefresh,
}: {
  runs: CaptureProgramTestRun[]
  openRun: string | null
  onOpen: (runId: string | null) => void
  onRefresh: () => void
}) {
  return (
    <Panel
      title="Test runs"
      actions={
        <Button variant="ghost" className="px-2" onClick={onRefresh} title="Refresh" aria-label="Refresh">
          <RefreshIcon size={16} />
        </Button>
      }
    >
      {runs.length === 0 ? (
        <p className="text-sm text-ink-muted">
          No test runs yet. <span className="text-ink">Test once</span> takes real frames with this program on the
          camera, outside production, and shows them here.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {runs.map((run) => (
            <div key={run.run_id} className="rounded-md border border-border-subtle">
              <button
                type="button"
                onClick={() => onOpen(openRun === run.run_id ? null : run.run_id)}
                className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-left hover:bg-surface-400/30"
              >
                <StatusBadge tone={RUN_TONES[run.status]}>{run.status}</StatusBadge>
                <span className="font-mono text-code-sm text-ink">
                  {new Date(run.finished_at ?? run.started_at ?? run.queued_at).toLocaleString()}
                </span>
                <span className="text-xs text-ink-muted">
                  {run.returned ? `${run.returned.kind} × ${run.returned.count}` : ''}
                  {run.duration_s != null ? ` · ${run.duration_s.toFixed(1)} s` : ''} · by {run.requested_by} ·{' '}
                  <span className="font-mono">{run.program.sha256.slice(0, 8)}</span>
                </span>
              </button>
              {openRun === run.run_id ? <TestRunDetail summary={run} /> : null}
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

function TestRunDetail({ summary }: { summary: CaptureProgramTestRun }) {
  // The list omits the log; the full report has it.
  const [run, setRun] = useState<CaptureProgramTestRun>(summary)
  useEffect(() => {
    let cancelled = false
    localApiClient.getCaptureProgramTestRun(summary.run_id).then(
      (full) => !cancelled && setRun(full),
      () => undefined,
    )
    return () => {
      cancelled = true
    }
  }, [summary])

  const fileUrl = (file: string) => localApiClient.captureProgramTestFileUrl(run.run_id, file)

  return (
    <div className="flex flex-col gap-3 border-t border-border-subtle p-3">
      {run.status === 'queued' || run.status === 'running' ? (
        <Message kind="info">
          {run.status === 'queued' ? 'Waiting for the next capture slot…' : 'Capturing…'}
        </Message>
      ) : null}
      {run.error ? (
        <Message kind="error">
          {run.error.type}: {run.error.message}
          {run.error.line ? ` (line ${run.error.line})` : ''}
        </Message>
      ) : null}
      {run.store_error ? <Message kind="error">Storing the frames failed: {run.store_error}</Message> : null}

      {run.frames?.length ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {run.frames.map((frame) => (
            <figure
              key={frame.file}
              className={[
                'overflow-hidden rounded-lg border bg-surface-0',
                frame.representative ? 'border-amber/60' : 'border-border',
              ].join(' ')}
            >
              <a href={fileUrl(frame.file)} target="_blank" rel="noreferrer">
                <img src={fileUrl(frame.file)} alt={`Frame ${frame.index}`} className="block aspect-[4/3] w-full object-cover" />
              </a>
              <figcaption className="flex flex-col gap-1 px-3 py-2">
                <span className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                  <span className="font-mono text-code-sm whitespace-nowrap text-ink">
                    {formatExposure(frame.exposure_us)} · ×{frame.analogue_gain.toFixed(2)}
                  </span>
                  {frame.representative ? <StatusBadge tone="info">Shown</StatusBadge> : null}
                </span>
                <span className="font-mono text-code-sm text-ink-muted">
                  #{frame.index} · median {frame.brightness_median}
                </span>
                {frame.capture_settings?.clamped?.length ? (
                  <span className="text-xs text-ink-muted">Clamped: {frame.capture_settings.clamped.join(', ')}</span>
                ) : null}
                {frame.capture_settings?.ignored?.length ? (
                  <span className="text-xs text-ink-muted">Ignored: {frame.capture_settings.ignored.join(', ')}</span>
                ) : null}
              </figcaption>
            </figure>
          ))}
        </div>
      ) : run.status === 'done' ? (
        <p className="text-sm text-ink-muted">The program returned nothing.</p>
      ) : null}

      {run.dng ? (
        <div>
          <a href={fileUrl(run.dng)} className={buttonClass('secondary')} download>
            <DownloadIcon size={16} />
            Raw DNG
          </a>
        </div>
      ) : null}
      {run.log?.length ? <LogBlock lines={run.log} /> : null}
    </div>
  )
}

function LogBlock({ lines }: { lines: string[] }) {
  return (
    <pre className="max-h-48 overflow-auto rounded-sm border border-border-subtle bg-surface-0 p-3 font-mono text-code-sm text-ink-muted">
      {lines.join('\n')}
    </pre>
  )
}

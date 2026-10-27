import { useEffect, useRef, useState } from 'react'
import { JsonEditor } from 'json-edit-react'
import type { AppConfig, ConfigImportResponse } from '@caelum/api-client'
import { Button, DOCS_URL, DownloadIcon, Loading, Message, PageHeader, Panel, buttonClass } from '@caelum/ui'
import { CameraPicker } from '../components/CameraPicker.tsx'
import { localApiClient } from '../services/client.ts'

/**
 * Sections a user should never structurally or value-edit from this tree:
 * `config_version` is server-managed, and `redis` is a connection setting
 * that the process reads once at startup, not a tunable parameter.
 *
 * `camera` is deliberately *not* locked any more: the capture thread now
 * reopens the device when this changes (see capture/worker.py's
 * `_ensure_camera`), so editing it here genuinely switches the camera. The
 * page renders a picker above the tree for it, because guessing a device
 * path is not a reasonable thing to ask of anyone.
 *
 * `auth` is not locked either — its policy flags are exactly what an
 * operator needs to change, and no credential material lives in this
 * document at all (accounts are stored separately; see the Accounts page).
 */
const LOCKED_SECTIONS = new Set(['config_version', 'redis'])

function isRawPeriodsPath(path: (string | number)[]): boolean {
  return path[0] === 'storage_policy' && path[1] === 'raw_periods'
}

export function Settings() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingImport | null>(null)
  const [importing, setImporting] = useState(false)
  const importRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let cancelled = false
    localApiClient
      .getConfig()
      .then((cfg) => {
        if (!cancelled) setConfig(cfg)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  /** Read the file and show what it would change — nothing is applied yet. */
  async function previewImport(file: File | undefined) {
    if (!file) return
    setMessage(null)
    setNotice(null)
    setPending(null)
    let parsed: unknown
    try {
      parsed = JSON.parse(await file.text())
    } catch (err) {
      setMessage(`${file.name} is not valid JSON: ${err instanceof Error ? err.message : String(err)}`)
      return
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      setMessage(`${file.name} must hold a JSON object — the whole config or some of its sections.`)
      return
    }
    try {
      const values = parsed as Record<string, unknown>
      const preview = await localApiClient.importConfig(values, true)
      if (preview.changes.length === 0) {
        setNotice(`${file.name} matches the current configuration — nothing to import.`)
      } else {
        setPending({ fileName: file.name, values, preview })
      }
    } catch (err) {
      setMessage(`${file.name} can't be imported: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  async function applyImport() {
    if (!pending) return
    setImporting(true)
    setMessage(null)
    try {
      const result = await localApiClient.importConfig(pending.values, false)
      setConfig(result.config)
      setNotice(`Imported ${plural(result.changes.length, 'value')} from ${pending.fileName}.`)
      setPending(null)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setImporting(false)
    }
  }

  if (loading) return <Loading label="Loading configuration…" />
  if (loadError) return <Message kind="error">{loadError}</Message>
  if (!config) return null

  return (
    <>
      <PageHeader
        title="Settings"
        description="The live configuration document. Changes save as you make them; greyed-out sections are read-only."
        actions={
          <>
            <a href={localApiClient.configExportUrl()} download className={buttonClass('secondary')}>
              <DownloadIcon size={16} />
              Export
            </a>
            <Button onClick={() => importRef.current?.click()}>Import…</Button>
            <input
              ref={importRef}
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={(e) => {
                void previewImport(e.target.files?.[0])
                e.target.value = ''
              }}
            />
            <a
              href={`${DOCS_URL}/guide/config-files.html#what-the-settings-mean`}
              target="_blank"
              rel="noreferrer noopener"
              className={buttonClass('secondary')}
            >
              What do these mean?
            </a>
          </>
        }
      />

      {message ? <Message kind="error">{message}</Message> : null}
      {notice ? <Message kind="success">{notice}</Message> : null}

      {pending ? (
        <Panel
          className="mt-2 mb-4"
          title={`Import ${pending.fileName}`}
          actions={
            <>
              <Button variant="ghost" onClick={() => setPending(null)} disabled={importing}>
                Cancel
              </Button>
              <Button variant="primary" onClick={() => void applyImport()} disabled={importing}>
                {importing ? 'Importing…' : `Apply ${plural(pending.preview.changes.length, 'change')}`}
              </Button>
            </>
          }
        >
          <p className="mb-3 text-sm text-ink-muted">
            Only the values in the file are set; everything else stays as it is.
            {pending.preview.ignored.length > 0
              ? ` Not imported: ${pending.preview.ignored.join(', ')} (always kept from this camera).`
              : ''}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-code-md">
              <thead>
                <tr className="text-left text-label-md text-ink-muted">
                  <th className="py-1 pr-4 font-normal">Setting</th>
                  <th className="py-1 pr-4 font-normal">Now</th>
                  <th className="py-1 font-normal">From the file</th>
                </tr>
              </thead>
              <tbody>
                {pending.preview.changes.map((change) => (
                  <tr key={change.path} className="border-t border-border-subtle align-top">
                    <td className="py-1 pr-4 text-ink">{change.path}</td>
                    <td className="py-1 pr-4 break-all text-ink-muted">{showValue(change.old)}</td>
                    <td className="py-1 break-all text-ink">{showValue(change.new)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      ) : null}

      <div className="mt-2 mb-4">
        <CameraPicker onConfigChange={setConfig} />
      </div>

      <div className="border border-border bg-panel p-2 rounded-md">
        <JsonEditor
          data={config}
          setData={(newData) => setConfig(newData as AppConfig)}
          rootName="config"
          theme={caelumJsonTheme}
          indent={2}
          collapse={2}
          restrictEdit={({ path }) => LOCKED_SECTIONS.has(String(path[0]))}
          restrictAdd={({ path }) => !isRawPeriodsPath(path)}
          restrictDelete={({ path }) => !(isRawPeriodsPath(path) && path.length === 3)}
          restrictTypeSelection={true}
          onUpdate={({ newData, currentData }) => {
            setMessage(null)
            localApiClient
              .updateConfig(newData as AppConfig)
              .then((updated) => setConfig(updated))
              .catch((err) => {
                setConfig(currentData as AppConfig)
                setMessage(err instanceof Error ? err.message : String(err))
              })
          }}
        />
      </div>
    </>
  )
}

interface PendingImport {
  fileName: string
  values: Record<string, unknown>
  preview: ConfigImportResponse
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

function showValue(value: unknown): string {
  return value === undefined ? '—' : JSON.stringify(value)
}

/**
 * json-edit-react takes inline style values, so every colour here is a
 * `var(--color-*)` reference into the shared token set rather than a literal
 * — that is what makes the editor follow the light/dark switch without this
 * file knowing anything about which theme is active.
 */
const caelumJsonTheme = {
  displayName: 'caelum',
  styles: {
    container: { backgroundColor: 'transparent', fontFamily: 'var(--font-mono)', fontSize: '13px' },
    property: 'var(--color-ink-muted)',
    bracket: { color: 'var(--color-ink-muted)', fontWeight: 'normal' },
    itemCount: { color: 'var(--color-ink-muted)', fontStyle: 'italic' },
    string: 'var(--color-sky)',
    number: 'var(--color-amber-ink)',
    boolean: 'var(--color-success)',
    null: { color: 'var(--color-error)', fontVariant: 'small-caps', fontWeight: 'bold' },
    input: [
      'var(--color-ink)',
      {
        fontSize: '95%',
        backgroundColor: 'var(--color-surface-0)',
        border: '1px solid var(--color-border)', borderRadius: '4px',
      },
    ],
    inputHighlight: 'var(--selection-bg)',
    error: { fontSize: '0.8em', color: 'var(--color-error)', fontWeight: 'bold' },
    iconCollection: 'var(--color-ink-muted)',
    iconEdit: 'var(--color-sky)',
    iconDelete: 'var(--color-error)',
    iconAdd: 'var(--color-sky)',
    iconCopy: 'var(--color-sky)',
    iconOk: 'var(--color-success)',
    iconCancel: 'var(--color-error)',
  },
}

import { useEffect, useState } from 'react'
import { JsonEditor } from 'json-edit-react'
import type { AppConfig } from '@caelum/api-client'
import { Loading, Message, PageHeader } from '@caelum/ui'
import { localApiClient } from '../services/client.ts'

/**
 * Sections a user should never structurally or value-edit from this tree:
 * `config_version` is server-managed; `camera` only takes effect on the
 * next process restart (editing it here would silently do nothing until
 * then, which is more confusing than just locking it); `redis` is a
 * connection setting, not a tunable parameter.
 *
 * Note what is *not* locked: `auth`. Its policy flags (who may see the
 * preview, whether the terminal is on) are exactly the things an operator
 * needs to change here — and no credential material lives in this document
 * at all, because accounts are stored separately (see the Accounts page).
 */
const LOCKED_SECTIONS = new Set(['config_version', 'camera', 'redis'])

function isRawPeriodsPath(path: (string | number)[]): boolean {
  return path[0] === 'storage_policy' && path[1] === 'raw_periods'
}

export function Settings() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

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

  if (loading) return <Loading label="Loading configuration…" />
  if (loadError) return <Message kind="error">{loadError}</Message>
  if (!config) return null

  return (
    <>
      <PageHeader
        title="Settings"
        description="The live configuration document. Changes save as you make them; greyed-out sections are read-only."
        actions={
          config.docs.base_url ? (
            <a
              href={`${config.docs.base_url}/guide/concepts.html`}
              target="_blank"
              rel="noreferrer noopener"
              className="border border-line px-3 py-1.5 text-xs tracking-wide text-ink-dim uppercase transition hover:border-amber-dim hover:text-ink"
            >
              What do these mean?
            </a>
          ) : null
        }
      />

      {message ? <Message kind="error">{message}</Message> : null}

      <div className="mt-2 border border-line bg-panel p-2">
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
    property: 'var(--color-ink-dim)',
    bracket: { color: 'var(--color-ink-faint)', fontWeight: 'normal' },
    itemCount: { color: 'var(--color-ink-faint)', fontStyle: 'italic' },
    string: 'var(--color-cyan)',
    number: 'var(--color-amber)',
    boolean: 'var(--color-success)',
    null: { color: 'var(--color-danger)', fontVariant: 'small-caps', fontWeight: 'bold' },
    input: [
      'var(--color-ink)',
      {
        fontSize: '95%',
        backgroundColor: 'var(--color-void)',
        border: '1px solid var(--color-line)',
      },
    ],
    inputHighlight: 'var(--selection-bg)',
    error: { fontSize: '0.8em', color: 'var(--color-danger)', fontWeight: 'bold' },
    iconCollection: 'var(--color-ink-faint)',
    iconEdit: 'var(--color-amber)',
    iconDelete: 'var(--color-danger)',
    iconAdd: 'var(--color-amber)',
    iconCopy: 'var(--color-cyan)',
    iconOk: 'var(--color-success)',
    iconCancel: 'var(--color-danger)',
  },
}

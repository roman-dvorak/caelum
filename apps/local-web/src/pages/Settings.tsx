import { useEffect, useState } from 'react'
import { JsonEditor } from 'json-edit-react'
import type { AppConfig } from '@caelum/api-client'
import { localApiClient } from '../services/client.ts'

/**
 * Sections a user should never structurally or value-edit from this tree:
 * `config_version` is server-managed; `camera` only takes effect on the
 * next process restart (editing it here would silently do nothing until
 * then, which is more confusing than just locking it); `redis` is a
 * connection setting, not a tunable parameter.
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

  if (loading) return <p className="text-sm text-ink-faint">Loading configuration…</p>
  if (loadError) {
    return <p className="border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{loadError}</p>
  }
  if (!config) return null

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-semibold tracking-[0.2em] text-ink-dim uppercase">Settings</h1>
        <span className="text-xs text-ink-faint">Changes save automatically</span>
      </div>
      {message ? (
        <p className="border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{message}</p>
      ) : null}

      <div className="border border-line bg-panel p-2">
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
    </div>
  )
}

const caelumJsonTheme = {
  displayName: 'caelum',
  styles: {
    container: { backgroundColor: 'transparent', fontFamily: 'var(--font-mono)', fontSize: '13px' },
    property: '#ab9d89',
    bracket: { color: '#6e6353', fontWeight: 'normal' },
    itemCount: { color: '#6e6353', fontStyle: 'italic' },
    string: '#6bb3c4',
    number: '#e8a13a',
    boolean: '#7cad76',
    null: { color: '#de6a56', fontVariant: 'small-caps', fontWeight: 'bold' },
    input: ['#f3ede1', { fontSize: '95%', backgroundColor: '#0b0a08', border: '1px solid #2f2a20' }],
    inputHighlight: 'rgba(232, 161, 58, 0.25)',
    error: { fontSize: '0.8em', color: '#de6a56', fontWeight: 'bold' },
    iconCollection: '#6e6353',
    iconEdit: '#e8a13a',
    iconDelete: '#de6a56',
    iconAdd: '#e8a13a',
    iconCopy: '#6bb3c4',
    iconOk: '#7cad76',
    iconCancel: '#de6a56',
  },
}

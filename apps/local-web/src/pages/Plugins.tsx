import { useEffect, useMemo, useState } from 'react'
import type { PluginsResponse } from '@caelum/api-client'
import { usePlugins } from '../hooks/usePlugins.ts'

interface PluginDraft {
  settingsText: string
  settingsError: string | null
}

export function Plugins() {
  const { plugins, error, loading, refresh, updatePlugin } = usePlugins()
  const [drafts, setDrafts] = useState<Record<string, PluginDraft>>({})
  const [busyId, setBusyId] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const orderedIds = useMemo(() => Object.keys(plugins ?? {}), [plugins])

  useEffect(() => {
    if (!plugins) return
    setDrafts((prev) => {
      const next = { ...prev }
      for (const [id, plugin] of Object.entries(plugins)) {
        if (!next[id]) {
          next[id] = { settingsText: JSON.stringify(plugin.settings, null, 2), settingsError: null }
        }
      }
      return next
    })
  }, [plugins])

  if (loading) return <p className="text-sm text-slate-500">Loading plugins…</p>
  if (error) {
    return <p className="rounded-md border border-red-900 bg-red-950/60 px-3 py-2 text-sm text-red-300">{error}</p>
  }
  if (!plugins || orderedIds.length === 0) {
    return <p className="text-sm text-slate-500">No plugins registered.</p>
  }

  async function toggleEnabled(id: string, enabled: boolean) {
    setBusyId(id)
    setMessage(null)
    try {
      await updatePlugin(id, { enabled })
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }

  async function move(id: string, direction: -1 | 1) {
    if (!plugins) return
    const index = orderedIds.indexOf(id)
    const swapIndex = index + direction
    if (swapIndex < 0 || swapIndex >= orderedIds.length) return
    const otherId = orderedIds[swapIndex]
    const thisOrder = plugins[id].order
    const otherOrder = plugins[otherId].order
    setBusyId(id)
    setMessage(null)
    try {
      await Promise.all([
        updatePlugin(id, { order: otherOrder }),
        updatePlugin(otherId, { order: thisOrder }),
      ])
      await refresh()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }

  async function saveSettings(id: string) {
    const draft = drafts[id]
    if (!draft) return
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(draft.settingsText) as Record<string, unknown>
    } catch (err) {
      setDrafts((prev) => ({
        ...prev,
        [id]: { ...prev[id], settingsError: err instanceof Error ? err.message : 'Invalid JSON' },
      }))
      return
    }
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], settingsError: null } }))
    setBusyId(id)
    setMessage(null)
    try {
      await updatePlugin(id, { settings: parsed })
      setMessage(`Saved settings for "${id}".`)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-lg font-semibold text-slate-100">Plugins</h1>
      {message ? <p className="text-sm text-slate-400">{message}</p> : null}

      <div className="flex flex-col gap-4">
        {orderedIds.map((id, index) => (
          <PluginCard
            key={id}
            id={id}
            plugins={plugins}
            index={index}
            total={orderedIds.length}
            busy={busyId === id}
            draft={drafts[id]}
            onToggleEnabled={(enabled) => void toggleEnabled(id, enabled)}
            onMove={(direction) => void move(id, direction)}
            onSettingsTextChange={(text) =>
              setDrafts((prev) => ({ ...prev, [id]: { settingsText: text, settingsError: null } }))
            }
            onSaveSettings={() => void saveSettings(id)}
          />
        ))}
      </div>
    </div>
  )
}

function PluginCard({
  id,
  plugins,
  index,
  total,
  busy,
  draft,
  onToggleEnabled,
  onMove,
  onSettingsTextChange,
  onSaveSettings,
}: {
  id: string
  plugins: PluginsResponse
  index: number
  total: number
  busy: boolean
  draft: PluginDraft | undefined
  onToggleEnabled: (enabled: boolean) => void
  onMove: (direction: -1 | 1) => void
  onSettingsTextChange: (text: string) => void
  onSaveSettings: () => void
}) {
  const plugin = plugins[id]
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="font-mono text-sm text-slate-100">{id}</span>
          <span className="text-xs text-slate-500">order {plugin.order}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onMove(-1)}
            disabled={busy || index === 0}
            title="Move up"
            className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            ↑
          </button>
          <button
            type="button"
            onClick={() => onMove(1)}
            disabled={busy || index === total - 1}
            title="Move down"
            className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            ↓
          </button>
          <label className="flex items-center gap-1.5 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={plugin.enabled}
              disabled={busy}
              onChange={(e) => onToggleEnabled(e.target.checked)}
              className="accent-sky-500"
            />
            Enabled
          </label>
        </div>
      </div>

      <label className="flex flex-col gap-1 text-sm text-slate-300">
        Settings (JSON)
        <textarea
          value={draft?.settingsText ?? '{}'}
          onChange={(e) => onSettingsTextChange(e.target.value)}
          rows={6}
          spellCheck={false}
          className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-100 focus:border-sky-500 focus:outline-none"
        />
      </label>
      {draft?.settingsError ? <p className="text-xs text-red-400">{draft.settingsError}</p> : null}

      <div>
        <button
          type="button"
          onClick={onSaveSettings}
          disabled={busy}
          className="rounded-md bg-sky-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Save settings
        </button>
      </div>
    </section>
  )
}

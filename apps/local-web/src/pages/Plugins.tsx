import { useMemo, useState } from 'react'
import type { PluginsResponse } from '@caelum/api-client'
import { usePlugins } from '../hooks/usePlugins.ts'

export function Plugins() {
  const { plugins, error, loading, refresh, updatePlugin } = usePlugins()
  const [busyId, setBusyId] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const orderedIds = useMemo(() => Object.keys(plugins ?? {}), [plugins])

  if (loading) return <p className="text-sm text-ink-faint">Loading plugins…</p>
  if (error) {
    return <p className="border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-sm font-semibold tracking-[0.2em] text-ink-dim uppercase">Plugins</h1>
      {message ? <p className="text-sm text-ink-dim">{message}</p> : null}

      {!plugins || orderedIds.length === 0 ? (
        <p className="border border-line bg-panel px-4 py-3 text-sm text-ink-faint">No plugins registered.</p>
      ) : (
        <div className="flex flex-col gap-4">
          {orderedIds.map((id, index) => (
            <PluginCard
              key={id}
              id={id}
              plugins={plugins}
              index={index}
              total={orderedIds.length}
              busy={busyId === id}
              onToggleEnabled={(enabled) => void toggleEnabled(id, enabled)}
              onMove={(direction) => void move(id, direction)}
              onSaveSettings={(settings) => void saveSettings(id, settings)}
            />
          ))}
        </div>
      )}
    </div>
  )

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

  async function saveSettings(id: string, settings: Record<string, unknown>) {
    setBusyId(id)
    setMessage(null)
    try {
      await updatePlugin(id, { settings })
      setMessage(`Saved settings for "${id}".`)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }
}

function PluginCard({
  id,
  plugins,
  index,
  total,
  busy,
  onToggleEnabled,
  onMove,
  onSaveSettings,
}: {
  id: string
  plugins: PluginsResponse
  index: number
  total: number
  busy: boolean
  onToggleEnabled: (enabled: boolean) => void
  onMove: (direction: -1 | 1) => void
  onSaveSettings: (settings: Record<string, unknown>) => void
}) {
  const plugin = plugins[id]
  // Seeded once from the plugin's settings at mount — this card's `key={id}`
  // in the parent means React gives each plugin its own instance/state, so
  // there's no need to re-sync this from props on every render.
  const [settingsText, setSettingsText] = useState(() => JSON.stringify(plugin.settings, null, 2))
  const [settingsError, setSettingsError] = useState<string | null>(null)

  function handleSave() {
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(settingsText) as Record<string, unknown>
    } catch (err) {
      setSettingsError(err instanceof Error ? err.message : 'Invalid JSON')
      return
    }
    setSettingsError(null)
    onSaveSettings(parsed)
  }

  return (
    <section className="flex flex-col gap-3 border border-line bg-panel p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="font-mono text-sm text-ink">{id}</span>
          <span className="font-mono text-xs text-ink-faint">order {plugin.order}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onMove(-1)}
            disabled={busy || index === 0}
            title="Move up"
            className="border border-line px-2 py-1 text-xs text-ink-dim hover:border-amber-dim hover:text-ink disabled:cursor-not-allowed disabled:opacity-30"
          >
            ↑
          </button>
          <button
            type="button"
            onClick={() => onMove(1)}
            disabled={busy || index === total - 1}
            title="Move down"
            className="border border-line px-2 py-1 text-xs text-ink-dim hover:border-amber-dim hover:text-ink disabled:cursor-not-allowed disabled:opacity-30"
          >
            ↓
          </button>
          <label className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-ink-dim uppercase">
            <input
              type="checkbox"
              checked={plugin.enabled}
              disabled={busy}
              onChange={(e) => onToggleEnabled(e.target.checked)}
              className="accent-amber"
            />
            Enabled
          </label>
        </div>
      </div>

      <label className="flex flex-col gap-1 text-xs font-medium tracking-wide text-ink-dim uppercase">
        Settings (JSON)
        <textarea
          value={settingsText}
          onChange={(e) => setSettingsText(e.target.value)}
          rows={6}
          spellCheck={false}
          className="border border-line bg-void px-3 py-2 font-mono text-xs font-normal tracking-normal text-ink normal-case focus:border-amber focus:outline-none"
        />
      </label>
      {settingsError ? <p className="text-xs text-danger">{settingsError}</p> : null}

      <div>
        <button
          type="button"
          onClick={handleSave}
          disabled={busy}
          className="bg-amber px-3 py-1.5 text-xs font-semibold tracking-wide text-void uppercase transition hover:bg-amber-bright disabled:cursor-not-allowed disabled:opacity-40"
        >
          Save settings
        </button>
      </div>
    </section>
  )
}

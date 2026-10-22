import { useMemo, useState } from 'react'
import type { PluginsResponse } from '@caelum/api-client'
import { Button, EmptyState, Loading, Message, PageHeader, StatusBadge, inputClass } from '@caelum/ui'
import { usePlugins } from '../hooks/usePlugins.ts'

export function Plugins() {
  const { plugins, error, loading, refresh, updatePlugin } = usePlugins()
  const [busyId, setBusyId] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const orderedIds = useMemo(() => Object.keys(plugins ?? {}), [plugins])

  if (loading) return <Loading label="Loading plugins…" />
  if (error) return <Message kind="error">{error}</Message>

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Plugins" description="Built-in and user plugins, in the order they run on each frame." />
      {message ? <Message kind="info">{message}</Message> : null}

      {!plugins || orderedIds.length === 0 ? (
        <EmptyState>No plugins registered.</EmptyState>
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
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-panel p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="font-display text-display-sm text-ink">{id}</span>
          <span className="font-mono text-code-sm text-ink-muted">order {plugin.order}</span>
          <StatusBadge tone={plugin.enabled ? 'success' : 'neutral'}>{plugin.enabled ? 'Enabled' : 'Off'}</StatusBadge>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => onMove(-1)} disabled={busy || index === 0} title="Move up" aria-label="Move up" className="px-2">
            ↑
          </Button>
          <Button variant="ghost" onClick={() => onMove(1)} disabled={busy || index === total - 1} title="Move down" aria-label="Move down" className="px-2">
            ↓
          </Button>
          <label className="flex items-center gap-1.5 text-label-md text-ink-muted">
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

      <label className="flex flex-col gap-1.5 text-label-md text-ink-muted">
        Settings (JSON)
        <textarea
          value={settingsText}
          onChange={(e) => setSettingsText(e.target.value)}
          rows={6}
          spellCheck={false}
          className={`${inputClass} text-code-sm font-normal`}
        />
      </label>
      {settingsError ? <p className="text-xs text-error">{settingsError}</p> : null}

      <div>
        <Button onClick={handleSave} disabled={busy}>
          Save settings
        </Button>
      </div>
    </section>
  )
}

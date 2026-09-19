import { useCallback, useEffect, useState } from 'react'
import type { PluginConfig, PluginUpdateRequest, PluginsResponse } from '@caelum/api-client'
import { localApiClient } from '../services/client.ts'

export interface UsePluginsResult {
  plugins: PluginsResponse | null
  error: string | null
  loading: boolean
  refresh: () => Promise<void>
  updatePlugin: (id: string, patch: PluginUpdateRequest) => Promise<PluginConfig>
}

export function usePlugins(): UsePluginsResult {
  const [plugins, setPlugins] = useState<PluginsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Exposed so callers (e.g. after a reorder) can force a refetch.
  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const next = await localApiClient.getPlugins()
      setPlugins(next)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      try {
        const next = await localApiClient.getPlugins()
        if (!cancelled) {
          setPlugins(next)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [])

  const updatePlugin = useCallback(async (id: string, patch: PluginUpdateRequest) => {
    const updated = await localApiClient.updatePlugin(id, patch)
    setPlugins((prev) => (prev ? { ...prev, [id]: updated } : prev))
    return updated
  }, [])

  return { plugins, error, loading, refresh, updatePlugin }
}

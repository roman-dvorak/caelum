import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { AuthContext as AuthContextPayload } from '@caelum/api-client'
import { AuthStateContext } from './authContext.ts'
import type { AuthState } from './authContext.ts'
import { localApiClient } from './services/client.ts'

/**
 * Owns "who am I on this camera".
 *
 * Everything hangs off `GET /api/auth/context`, which is deliberately
 * unauthenticated: the SPA has to be able to ask whether this deployment
 * even requires a login (`auth.enabled`) and whether the preview is public,
 * before it can decide whether to render a login form or go straight to the
 * dashboard.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [context, setContext] = useState<AuthContextPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      try {
        const next = await localApiClient.getAuthContext()
        if (!cancelled) {
          setContext(next)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void bootstrap()
    return () => {
      cancelled = true
    }
  }, [])

  // Called from event handlers only, never from an effect.
  const refresh = useCallback(async () => {
    setContext(await localApiClient.getAuthContext())
    setError(null)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    setContext(await localApiClient.login(username, password))
    setError(null)
  }, [])

  const logout = useCallback(async () => {
    await localApiClient.logout()
    setContext(await localApiClient.getAuthContext())
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      context,
      loading,
      error,
      // With auth switched off the backend reports everyone as an admin, so
      // the UI needs no separate "auth disabled" branch anywhere else.
      isAuthenticated: context?.authenticated ?? false,
      isAdmin: context?.role === 'admin',
      login,
      logout,
      refresh,
    }),
    [context, loading, error, login, logout, refresh],
  )

  return <AuthStateContext value={value}>{children}</AuthStateContext>
}

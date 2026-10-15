/** Auth state shape and the hook that reads it. Split from auth.tsx so that
 * file exports only components (react-refresh requires the split). */

import { createContext, useContext } from 'react'
import type { AuthContext as AuthContextPayload } from '@caelum/api-client'

export interface AuthState {
  /** null until the first `/api/auth/context` call resolves. */
  context: AuthContextPayload | null
  loading: boolean
  /** The backend is unreachable — distinct from "not signed in". */
  error: string | null
  isAuthenticated: boolean
  isAdmin: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

export const AuthStateContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const state = useContext(AuthStateContext)
  if (!state) throw new Error('useAuth() must be used inside an <AuthProvider>')
  return state
}

import { useState } from 'react'
import { Button, Field, Message, inputClass } from '@caelum/ui'
import { useAuth } from '../authContext.ts'

export function Login() {
  const { login, context } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
    } catch (err) {
      setError(err instanceof Error ? err.message.replace(/^caelum API request failed:.*?\(/, '').replace(/\)$/, '') : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-svh items-center justify-center p-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm border border-line bg-panel p-6 shadow-[var(--shadow-panel)]"
      >
        <div className="mb-6 flex items-baseline gap-2">
          <span className="h-1.5 w-1.5 translate-y-[-0.15em] rounded-full bg-amber shadow-[0_0_8px_var(--color-amber)]" />
          <span className="text-sm font-semibold tracking-[0.2em] text-ink uppercase">caelum</span>
        </div>

        <div className="flex flex-col gap-4">
          <Field label="Username">
            <input
              className={inputClass}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
            />
          </Field>
          <Field label="Password">
            <input
              className={inputClass}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>

          {error ? <Message kind="error">{error}</Message> : null}

          <Button type="submit" variant="primary" disabled={busy} className="py-2">
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>

          {context?.preview_access === 'public' ? (
            <p className="text-center text-xs text-ink-faint">
              The live preview on this camera is public — sign in only to control it.
            </p>
          ) : null}

          {context?.docs_url ? (
            <a
              href={`${context.docs_url}/guide/security.html`}
              target="_blank"
              rel="noreferrer noopener"
              className="text-center text-xs text-ink-faint underline decoration-line underline-offset-4 hover:text-ink"
            >
              Forgot the password?
            </a>
          ) : null}
        </div>
      </form>
    </div>
  )
}

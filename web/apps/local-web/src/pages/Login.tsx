import { useState } from 'react'
import { Button, DOCS_URL, Field, Message, inputClass } from '@caelum/ui'
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
      <form onSubmit={handleSubmit} className="w-full max-w-sm overflow-hidden rounded-xl border border-border bg-panel shadow-lg">
        <div className="flex flex-col items-center gap-1.5 bg-navy px-6 py-6 text-on-navy">
          <span className="text-label-sm tracking-[0.2em] uppercase opacity-75">AstroMeters</span>
          <span className="flex items-center gap-2.5">
            <span className="h-1.5 w-1.5 rounded-full bg-amber shadow-glow-amber" />
            <span className="font-display text-display-xl tracking-[-0.03em]">caelum</span>
          </span>
          <span className="text-xs opacity-75">Allsky camera software</span>
        </div>

        <div className="flex flex-col gap-4 p-6">
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
            <p className="text-center text-xs text-ink-muted">
              The live preview on this camera is public — sign in only to control it.
            </p>
          ) : null}

          <a
            href={`${DOCS_URL}/guide/security.html`}
            target="_blank"
            rel="noreferrer noopener"
            className="text-center text-xs text-sky underline-offset-4 hover:underline"
          >
            Forgot the password?
          </a>
        </div>
      </form>
    </div>
  )
}

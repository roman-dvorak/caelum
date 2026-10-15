import { useCallback, useEffect, useState } from 'react'
import type { Role, UserSummary } from '@caelum/api-client'
import {
  Button,
  Field,
  Loading,
  Message,
  PageHeader,
  Panel,
  TrashIcon,
  formatTimestamp,
  inputClass,
} from '@caelum/ui'
import { useAuth } from '../authContext.ts'
import { localApiClient } from '../services/client.ts'

export function Users() {
  const { context } = useAuth()
  const [users, setUsers] = useState<UserSummary[] | null>(null)
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)

  const [reloadToken, setReloadToken] = useState(0)
  const load = useCallback(async () => setReloadToken((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false

    async function run() {
      try {
        const next = await localApiClient.listUsers()
        if (!cancelled) setUsers(next)
      } catch (err) {
        if (!cancelled) {
          setMessage({ kind: 'error', text: err instanceof Error ? err.message : String(err) })
        }
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [reloadToken])

  const report = (err: unknown) =>
    setMessage({ kind: 'error', text: err instanceof Error ? err.message : String(err) })

  return (
    <>
      <PageHeader
        title="Accounts"
        description="Administrators control the camera; viewers only see the preview. Account details are stored outside the main config, so they never appear in the Settings editor."
      />

      {message ? <Message kind={message.kind}>{message.text}</Message> : null}

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_20rem]">
        <Panel title="Users" bodyClassName="">
          {users === null ? (
            <div className="p-4">
              <Loading />
            </div>
          ) : (
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="text-left text-[0.65rem] tracking-[0.15em] text-ink-faint uppercase">
                  <th className="px-4 py-2 font-medium">User</th>
                  <th className="px-2 py-2 font-medium">Role</th>
                  <th className="hidden px-2 py-2 font-medium sm:table-cell">Last login</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.username} className="border-t border-line-soft">
                    <td className="px-4 py-2 font-mono text-ink">
                      {user.username}
                      {user.username === context?.username ? (
                        <span className="ml-2 text-xs text-ink-faint">(you)</span>
                      ) : null}
                    </td>
                    <td className="px-2 py-2">
                      <select
                        value={user.role}
                        onChange={(e) => {
                          localApiClient
                            .updateUser(user.username, { role: e.target.value as Role })
                            .then(load)
                            .catch(report)
                        }}
                        className="border border-line bg-void px-2 py-1 text-xs text-ink"
                      >
                        <option value="admin">admin</option>
                        <option value="viewer">viewer</option>
                      </select>
                    </td>
                    <td className="hidden px-2 py-2 font-mono text-xs text-ink-faint sm:table-cell">
                      {formatTimestamp(user.last_login_at)}
                    </td>
                    <td className="px-2 py-2 text-right">
                      {user.username === context?.username ? null : (
                        <button
                          type="button"
                          title={`Delete ${user.username}`}
                          onClick={() => {
                            if (!window.confirm(`Delete account "${user.username}"?`)) return
                            localApiClient.deleteUser(user.username).then(load).catch(report)
                          }}
                          className="p-1 text-ink-faint transition hover:text-danger"
                        >
                          <TrashIcon size={15} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <div className="flex flex-col gap-4">
          <CreateUserForm
            onCreated={() => {
              setMessage({ kind: 'success', text: 'Account created.' })
              void load()
            }}
            onError={report}
          />
          <ChangePasswordForm
            onDone={() => setMessage({ kind: 'success', text: 'Password changed. Other sessions signed out.' })}
            onError={report}
          />
        </div>
      </div>
    </>
  )
}

function CreateUserForm({
  onCreated,
  onError,
}: {
  onCreated: () => void
  onError: (err: unknown) => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<Role>('viewer')

  return (
    <Panel title="Add account">
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          localApiClient
            .createUser(username, password, role)
            .then(() => {
              setUsername('')
              setPassword('')
              onCreated()
            })
            .catch(onError)
        }}
      >
        <Field label="Username">
          <input
            className={inputClass}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="off"
            required
          />
        </Field>
        <Field label="Password" hint="At least 8 characters.">
          <input
            className={inputClass}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            required
          />
        </Field>
        <Field label="Role">
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
            className={inputClass}
          >
            <option value="viewer">viewer — preview only</option>
            <option value="admin">admin — full control</option>
          </select>
        </Field>
        <Button type="submit" variant="primary">
          Create account
        </Button>
      </form>
    </Panel>
  )
}

function ChangePasswordForm({
  onDone,
  onError,
}: {
  onDone: () => void
  onError: (err: unknown) => void
}) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')

  return (
    <Panel title="Change your password">
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          localApiClient
            .changePassword(current, next)
            .then(() => {
              setCurrent('')
              setNext('')
              onDone()
            })
            .catch(onError)
        }}
      >
        <Field label="Current password">
          <input
            className={inputClass}
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
            required
          />
        </Field>
        <Field label="New password" hint="Signs out every other device.">
          <input
            className={inputClass}
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
            required
          />
        </Field>
        <Button type="submit">Change password</Button>
      </form>
    </Panel>
  )
}

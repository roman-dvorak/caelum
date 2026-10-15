import { useEffect, useRef, useState } from 'react'
import { FitAddon } from '@xterm/addon-fit'
import { Terminal as XTerm } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { connectTerminal } from '@caelum/api-client'
import type { TerminalSessionHandle } from '@caelum/api-client'
import { Button, Message, PageHeader, RefreshIcon, useTheme } from '@caelum/ui'
import { useAuth } from '../authContext.ts'

type ConnectionState = 'connecting' | 'open' | 'closed' | 'denied'

/** xterm needs literal colors, not `var(--…)`, so the two palettes are
 * mirrored here from packages/ui/src/theme.css. */
const XTERM_THEMES = {
  dark: {
    background: '#0b0a08',
    foreground: '#f3ede1',
    cursor: '#e8a13a',
    cursorAccent: '#0b0a08',
    selectionBackground: 'rgba(232, 161, 58, 0.3)',
    black: '#16130f',
    red: '#de6a56',
    green: '#7cad76',
    yellow: '#e8a13a',
    blue: '#6bb3c4',
    magenta: '#c08ac4',
    cyan: '#6bb3c4',
    white: '#ab9d89',
    brightBlack: '#6e6353',
    brightYellow: '#ffc266',
    brightWhite: '#f3ede1',
  },
  light: {
    background: '#ffffff',
    foreground: '#1b1712',
    cursor: '#a9690f',
    cursorAccent: '#ffffff',
    selectionBackground: 'rgba(169, 105, 15, 0.22)',
    black: '#1b1712',
    red: '#b23a26',
    green: '#3c7336',
    yellow: '#a9690f',
    blue: '#276476',
    magenta: '#8a4a90',
    cyan: '#276476',
    white: '#5d5346',
    brightBlack: '#8d8271',
    brightYellow: '#855009',
    brightWhite: '#1b1712',
  },
} as const

export function TerminalPage() {
  const { context } = useAuth()
  const { theme } = useTheme()
  const hostRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<XTerm | null>(null)
  const [state, setState] = useState<ConnectionState>('connecting')
  const [generation, setGeneration] = useState(0)

  const enabled = context?.terminal_enabled !== false

  useEffect(() => {
    if (!enabled || !hostRef.current) return

    const term = new XTerm({
      fontFamily:
        "ui-monospace, 'Cascadia Code', 'SF Mono', 'Roboto Mono', Consolas, monospace",
      fontSize: 13,
      cursorBlink: true,
      scrollback: 5000,
      theme: XTERM_THEMES[theme],
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(hostRef.current)
    fit.fit()
    termRef.current = term

    let session: TerminalSessionHandle | null = null
    setState('connecting')

    session = connectTerminal({
      onData: (chunk) => term.write(chunk),
      onOpen: () => {
        setState('open')
        // The PTY starts at 80x24; tell it the real size before the shell
        // draws its first prompt, or long command lines wrap wrongly.
        session?.resize(term.cols, term.rows)
        term.focus()
      },
      onClose: (event) => {
        // 1008 is the policy-violation code the backend closes with when the
        // caller is not an admin or the terminal is switched off.
        setState(event.code === 1008 ? 'denied' : 'closed')
      },
    })

    term.onData((data) => session?.send(data))
    term.onResize(({ cols, rows }) => session?.resize(cols, rows))

    const observer = new ResizeObserver(() => {
      try {
        fit.fit()
      } catch {
        /* the host is detached mid-teardown — nothing to fit */
      }
    })
    observer.observe(hostRef.current)

    return () => {
      observer.disconnect()
      session?.close()
      term.dispose()
      termRef.current = null
    }
    // `generation` is the reconnect trigger: bumping it tears the whole
    // session down and builds a fresh one.
  }, [enabled, theme, generation])

  if (!enabled) {
    return (
      <>
        <PageHeader title="Terminal" />
        <Message kind="info">
          The web terminal is disabled on this camera (<code>auth.terminal_enabled</code> is false in
          Settings).
        </Message>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Terminal"
        description="Interactive shell on the camera host, running as the caelum service user. Starts in the data directory."
        actions={
          <>
            <StatusPill state={state} />
            <Button icon={<RefreshIcon size={14} />} onClick={() => setGeneration((n) => n + 1)}>
              Reconnect
            </Button>
          </>
        }
      />

      {state === 'denied' ? (
        <Message kind="error">
          The server refused the terminal session — administrator access is required.
        </Message>
      ) : null}

      <div
        className="border border-line bg-panel p-2"
        // xterm measures its own host, so it needs a concrete height rather
        // than one that depends on its content.
        style={{ height: 'min(70svh, 40rem)' }}
      >
        <div ref={hostRef} className="h-full w-full" />
      </div>
    </>
  )
}

function StatusPill({ state }: { state: ConnectionState }) {
  const styles: Record<ConnectionState, string> = {
    connecting: 'border-line text-ink-faint',
    open: 'border-success/50 text-success',
    closed: 'border-line text-ink-faint',
    denied: 'border-danger/50 text-danger',
  }
  const labels: Record<ConnectionState, string> = {
    connecting: 'Connecting',
    open: 'Connected',
    closed: 'Disconnected',
    denied: 'Refused',
  }
  return (
    <span className={`border px-2 py-1 text-[0.65rem] tracking-[0.15em] uppercase ${styles[state]}`}>
      {labels[state]}
    </span>
  )
}

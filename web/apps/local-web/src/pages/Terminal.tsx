import { useEffect, useRef, useState } from 'react'
import { FitAddon } from '@xterm/addon-fit'
import { Terminal as XTerm } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { connectTerminal } from '@caelum/api-client'
import type { TerminalSessionHandle } from '@caelum/api-client'
import { Button, Message, PageHeader, RefreshIcon, StatusBadge, useTheme } from '@caelum/ui'
import { useAuth } from '../authContext.ts'

type ConnectionState = 'connecting' | 'open' | 'closed' | 'denied'

/** xterm needs literal colors, not `var(--…)`: the Caelum design system's
 * tokens (packages/ui/src/theme.css), mirrored here. ANSI colours map to the
 * nearest token — red `error`, green `success`, yellow `amber`, blue and
 * cyan `sky`, magenta `nebula`'s lighter `sky-dim` pairing. */
const XTERM_THEMES = {
  dark: {
    background: '#070a10', // surface-0
    foreground: '#e2e8f5', // ink
    cursor: '#e8a13a', // amber
    cursorAccent: '#070a10',
    selectionBackground: 'rgba(232, 161, 58, 0.28)',
    black: '#141a24', // surface-200
    red: '#e85a4a', // error
    green: '#2ecc9a', // success
    yellow: '#e8a13a', // amber
    blue: '#5a8ee8', // sky
    magenta: '#8a9db8', // ink-muted
    cyan: '#5a8ee8', // sky
    white: '#8a9db8', // ink-muted
    brightBlack: '#4a5e78', // ink-dim
    brightRed: '#e85a4a',
    brightGreen: '#2ecc9a',
    brightYellow: '#f5c96a', // amber-light
    brightBlue: '#5a8ee8',
    brightCyan: '#5a8ee8',
    brightWhite: '#e2e8f5', // ink
  },
  light: {
    background: '#ffffff', // surface-100
    foreground: '#0d1117', // ink
    cursor: '#a06820', // amber-dim
    cursorAccent: '#ffffff',
    selectionBackground: 'rgba(196, 131, 42, 0.22)',
    black: '#0d1117', // ink
    red: '#c03020', // error
    green: '#1aaa78', // success
    yellow: '#a06820', // amber-dim
    blue: '#2a5aaa', // sky-dim
    magenta: '#4a5e78', // ink-muted
    cyan: '#2a5aaa', // sky-dim
    white: '#4a5e78', // ink-muted
    brightBlack: '#8a9db8', // ink-dim
    brightRed: '#c03020',
    brightGreen: '#1aaa78',
    brightYellow: '#a06820',
    brightBlue: '#3a6ec8', // sky
    brightCyan: '#3a6ec8',
    brightWhite: '#0d1117',
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
      fontFamily: "'JetBrains Mono Variable', 'JetBrains Mono', ui-monospace, monospace",
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
        className="border border-border bg-panel p-2 rounded-md"
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
  const tones = { connecting: 'neutral', open: 'success', closed: 'neutral', denied: 'error' } as const
  const labels: Record<ConnectionState, string> = {
    connecting: 'Connecting',
    open: 'Connected',
    closed: 'Disconnected',
    denied: 'Refused',
  }
  return (
    <StatusBadge tone={tones[state]}>{labels[state]}</StatusBadge>
  )
}

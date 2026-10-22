import { useEffect, useMemo, useRef, useState } from 'react'
import { connectLogs } from '@caelum/api-client'
import type { LogEntry } from '@caelum/api-client'
import { Button, Field, Message, PageHeader, PauseIcon, PlayIcon, RefreshIcon, StatusBadge, TrashIcon, buttonClass, inputClass } from '@caelum/ui'

type ConnectionState = 'connecting' | 'open' | 'closed'
type LevelFilter = 'ALL' | 'INFO' | 'WARNING' | 'ERROR'

const LEVEL_STYLES: Record<string, string> = {
  DEBUG: 'text-ink-muted',
  INFO: 'text-ink-muted',
  WARNING: 'text-amber-ink',
  ERROR: 'text-error',
  CRITICAL: 'text-error font-semibold',
}

const LEVEL_RANK: Record<string, number> = { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3, CRITICAL: 4 }
const LEVEL_THRESHOLD: Record<LevelFilter, number> = { ALL: -1, INFO: 1, WARNING: 2, ERROR: 3 }

// Enough to search/scroll through a real session without the DOM or memory
// growing without bound on a camera that's been up for weeks.
const MAX_LINES = 5000

/**
 * Live tail of everything caelum has logged since it started — the
 * `journalctl -u caelum -f` a headless camera has no console to run.
 */
export function Logs() {
  // Reconnecting remounts the view (fresh key) instead of resetting state
  // inside an effect: every piece of state and both refs in LogsView
  // legitimately need to go back to their initial values together, which a
  // remount gives for free rather than a growing list of manual resets.
  const [generation, setGeneration] = useState(0)
  return <LogsView key={generation} onReconnect={() => setGeneration((n) => n + 1)} />
}

function LogsView({ onReconnect }: { onReconnect: () => void }) {
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [state, setState] = useState<ConnectionState>('connecting')
  const [paused, setPaused] = useState(false)
  const [heldCount, setHeldCount] = useState(0)
  const [level, setLevel] = useState<LevelFilter>('ALL')
  const [search, setSearch] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)

  // `onEntry` is a closure captured once, when the socket connects, so it
  // reads `paused` through a ref — kept in sync from `togglePause` below
  // (an event handler, never written during render) — rather than the
  // stale value closed over at connect time.
  const pausedRef = useRef(false)
  const heldRef = useRef<LogEntry[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const session = connectLogs({
      onOpen: () => setState('open'),
      onClose: () => setState('closed'),
      onBacklog: (backlog) => setEntries(backlog.slice(-MAX_LINES)),
      onEntry: (entry) => {
        // While paused, new lines are held here rather than appended, so
        // the visible scrollback stays exactly still until resumed.
        if (pausedRef.current) {
          heldRef.current.push(entry)
          setHeldCount(heldRef.current.length)
          return
        }
        setEntries((current) => {
          const next = [...current, entry]
          return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next
        })
      },
    })

    return () => session.close()
  }, [])

  function togglePause() {
    setPaused((current) => {
      const next = !current
      pausedRef.current = next
      if (current) {
        // Resuming: flush everything held back while paused, in one go.
        const held = heldRef.current
        heldRef.current = []
        setHeldCount(0)
        if (held.length) {
          setEntries((existing) => {
            const merged = [...existing, ...held]
            return merged.length > MAX_LINES ? merged.slice(merged.length - MAX_LINES) : merged
          })
        }
      }
      return next
    })
  }

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return entries.filter((entry) => {
      if (level !== 'ALL' && (LEVEL_RANK[entry.level] ?? 0) < LEVEL_THRESHOLD[level]) return false
      if (!needle) return true
      return entry.message.toLowerCase().includes(needle) || entry.logger.toLowerCase().includes(needle)
    })
  }, [entries, level, search])

  useEffect(() => {
    if (!autoScroll || !scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [filtered, autoScroll])

  function handleScroll() {
    const el = scrollRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
    setAutoScroll(atBottom)
  }

  function downloadVisible() {
    const text = filtered.map((e) => `${e.timestamp} ${e.level.padEnd(8)} ${e.logger}: ${e.message}`).join('\n')
    const blob = new Blob([text], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `caelum-logs-${new Date().toISOString().replace(/[:.]/g, '-')}.txt`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <PageHeader
        title="Logs"
        description="Everything caelum has logged since it started, live."
        actions={
          <>
            <StatusPill state={state} paused={paused} heldCount={heldCount} />
            <Button
              icon={paused ? <PlayIcon size={14} /> : <PauseIcon size={14} />}
              onClick={togglePause}
            >
              {paused ? 'Resume' : 'Pause'}
            </Button>
            <Button icon={<TrashIcon size={14} />} onClick={() => setEntries([])}>
              Clear
            </Button>
            <Button icon={<RefreshIcon size={14} />} onClick={onReconnect}>
              Reconnect
            </Button>
          </>
        }
      />

      {state === 'closed' ? (
        <Message kind="error">
          Disconnected from the log stream. Administrator access is required — sign back in if your
          session expired.
        </Message>
      ) : null}

      <div className="mb-3 flex flex-wrap items-end gap-3">
        <Field label="Level">
          <select
            value={level}
            onChange={(e) => setLevel(e.target.value as LevelFilter)}
            className={inputClass}
          >
            <option value="ALL">All</option>
            <option value="INFO">Info and above</option>
            <option value="WARNING">Warning and above</option>
            <option value="ERROR">Error and above</option>
          </select>
        </Field>
        <Field label="Search">
          <input
            className={inputClass}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="message or logger name"
          />
        </Field>
        <Button onClick={downloadVisible} disabled={filtered.length === 0} className="mb-px">
          Download shown ({filtered.length})
        </Button>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="h-[65svh] overflow-y-auto border border-border bg-surface-0 p-3 font-mono text-xs leading-relaxed rounded-md"
      >
        {filtered.length === 0 ? (
          <p className="text-ink-muted">
            {entries.length === 0 ? 'Waiting for log output…' : 'No lines match the current filter.'}
          </p>
        ) : (
          filtered.map((entry, index) => <LogLine key={index} entry={entry} />)
        )}
      </div>

      {!autoScroll ? (
        <button
          type="button"
          onClick={() => {
            setAutoScroll(true)
            if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
          }}
          className={buttonClass('secondary', 'mt-2 w-full')}
        >
          Scrolled up — click to jump to the latest
        </button>
      ) : null}
    </>
  )
}

function LogLine({ entry }: { entry: LogEntry }) {
  const time = entry.timestamp.slice(11, 23) || entry.timestamp
  return (
    <div className="flex gap-2 whitespace-pre-wrap break-all border-b border-border-subtle/40 py-0.5 last:border-b-0">
      <span className="shrink-0 text-ink-muted tabular-nums">{time}</span>
      <span className={`w-16 shrink-0 font-semibold ${LEVEL_STYLES[entry.level] ?? 'text-ink-muted'}`}>
        {entry.level}
      </span>
      <span className="shrink-0 text-sky">{entry.logger}</span>
      <span className="text-ink">{entry.message}</span>
    </div>
  )
}

function StatusPill({
  state,
  paused,
  heldCount,
}: {
  state: ConnectionState
  paused: boolean
  heldCount: number
}) {
  if (paused) {
    return (
      <StatusBadge tone="warning">Paused{heldCount ? ` · +${heldCount}` : ''}</StatusBadge>
    )
  }
  const tones = { connecting: 'neutral', open: 'success', closed: 'error' } as const
  const labels: Record<ConnectionState, string> = {
    connecting: 'Connecting',
    open: 'Live',
    closed: 'Disconnected',
  }
  return (
    <StatusBadge tone={tones[state]}>{labels[state]}</StatusBadge>
  )
}

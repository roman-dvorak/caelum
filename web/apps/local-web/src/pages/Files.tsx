import { useCallback, useEffect, useState } from 'react'
import type { DirectoryListing, FileEntry, UsageResponse } from '@caelum/api-client'
import {
  Button,
  DownloadIcon,
  EmptyState,
  FolderIcon,
  Loading,
  Message,
  PageHeader,
  Panel,
  Readout,
  RefreshIcon,
  TrashIcon,
  formatBytes,
  formatTimestamp,
} from '@caelum/ui'
import { useAuth } from '../authContext.ts'
import { localApiClient } from '../services/client.ts'

/**
 * Generic browser over the whole data directory.
 *
 * Complements the recordings manager rather than duplicating it: that page
 * knows what a capture *is*, this one shows whatever is actually on disk —
 * dark frames, keograms, stray files, anything a plugin wrote — which is
 * what you want when something is taking up space and you do not yet know
 * what it is.
 */
export function Files() {
  const { isAdmin } = useAuth()
  const [path, setPath] = useState('')
  const [listing, setListing] = useState<DirectoryListing | null>(null)
  const [usage, setUsage] = useState<UsageResponse | null>(null)
  const [selected, setSelected] = useState<FileEntry | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Bumped to re-run the directory fetch without changing `path` — the
  // refresh button and post-delete reload both go through it, which keeps
  // all the state updates inside the effect's own async function.
  const [reloadToken, setReloadToken] = useState(0)
  const refresh = useCallback(() => setReloadToken((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false

    async function run() {
      setLoading(true)
      try {
        const next = await localApiClient.listFiles(path)
        if (!cancelled) {
          setListing(next)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [path, reloadToken])

  useEffect(() => {
    let cancelled = false
    localApiClient
      .getUsage()
      .then((next) => {
        if (!cancelled) setUsage(next)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [reloadToken])

  async function handleDelete(entry: FileEntry) {
    const what = entry.kind === 'dir' ? `directory "${entry.name}" and everything in it` : entry.name
    if (!window.confirm(`Delete ${what}? This cannot be undone.`)) return
    try {
      await localApiClient.deletePath(entry.path)
      if (selected?.path === entry.path) setSelected(null)
      refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <>
      <PageHeader
        title="Files"
        description="Everything stored on this camera, as it sits on disk."
        actions={
          <Button icon={<RefreshIcon size={14} />} onClick={refresh}>
            Refresh
          </Button>
        }
      />

      {usage ? (
        <div className="mb-4 grid grid-cols-2 gap-3 border border-line bg-panel p-4 sm:grid-cols-3 lg:grid-cols-6">
          {Object.entries(usage.by_subdir).map(([name, bytes]) => (
            <Readout key={name} label={name} value={formatBytes(bytes)} />
          ))}
          <Readout label="Stored" value={formatBytes(usage.total_bytes)} />
          <Readout
            label="Disk free"
            value={`${formatBytes(usage.disk_free_bytes)} / ${formatBytes(usage.disk_total_bytes)}`}
          />
        </div>
      ) : null}

      {error ? <Message kind="error">{error}</Message> : null}

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <Panel title={<Breadcrumbs path={path} onNavigate={setPath} />} bodyClassName="">
          {loading && !listing ? (
            <Loading />
          ) : !listing || listing.entries.length === 0 ? (
            <EmptyState>This directory is empty.</EmptyState>
          ) : (
            <table className="w-full border-collapse text-sm">
              <tbody>
                {listing.parent !== null ? (
                  <tr>
                    <td colSpan={4} className="border-b border-line-soft">
                      <button
                        type="button"
                        onClick={() => setPath(listing.parent ?? '')}
                        className="w-full px-4 py-2 text-left font-mono text-ink-dim hover:bg-panel-raised hover:text-ink"
                      >
                        ../
                      </button>
                    </td>
                  </tr>
                ) : null}
                {listing.entries.map((entry) => (
                  <tr
                    key={entry.path}
                    className={[
                      'border-b border-line-soft last:border-b-0',
                      selected?.path === entry.path ? 'bg-amber/8' : 'hover:bg-panel-raised',
                    ].join(' ')}
                  >
                    <td className="w-full">
                      <button
                        type="button"
                        onClick={() =>
                          entry.kind === 'dir' ? setPath(entry.path) : setSelected(entry)
                        }
                        className="flex w-full items-center gap-2 px-4 py-2 text-left font-mono text-ink"
                      >
                        {entry.kind === 'dir' ? (
                          <FolderIcon size={15} className="shrink-0 text-amber" />
                        ) : (
                          <span className="w-[15px]" />
                        )}
                        <span className="truncate">{entry.name}</span>
                      </button>
                    </td>
                    <td className="px-2 text-right font-mono text-xs whitespace-nowrap text-ink-faint tabular-nums">
                      {entry.kind === 'dir' ? '—' : formatBytes(entry.size)}
                    </td>
                    <td className="hidden px-2 text-right font-mono text-xs whitespace-nowrap text-ink-faint sm:table-cell">
                      {formatTimestamp(entry.modified_at)}
                    </td>
                    <td className="px-2 text-right">
                      {isAdmin ? (
                        <button
                          type="button"
                          onClick={() => void handleDelete(entry)}
                          title={`Delete ${entry.name}`}
                          className="p-1 text-ink-faint transition hover:text-danger"
                        >
                          <TrashIcon size={15} />
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        {/* Keyed by path: selecting a different file remounts the panel, so
            its fetched preview text resets without a synchronising effect. */}
        <FileDetail key={selected?.path ?? '·none·'} entry={selected} />
      </div>
    </>
  )
}

function Breadcrumbs({ path, onNavigate }: { path: string; onNavigate: (path: string) => void }) {
  const parts = path ? path.split('/') : []
  return (
    <span className="flex flex-wrap items-center gap-1 font-mono text-xs normal-case">
      <button
        type="button"
        onClick={() => onNavigate('')}
        className="text-amber hover:text-amber-bright"
      >
        data
      </button>
      {parts.map((part, index) => (
        <span key={`${part}-${index}`} className="flex items-center gap-1">
          <span className="text-ink-faint">/</span>
          <button
            type="button"
            onClick={() => onNavigate(parts.slice(0, index + 1).join('/'))}
            className={index === parts.length - 1 ? 'text-ink' : 'text-amber hover:text-amber-bright'}
          >
            {part}
          </button>
        </span>
      ))}
    </span>
  )
}

function FileDetail({ entry }: { entry: FileEntry | null }) {
  const [text, setText] = useState<string | null>(null)

  // Small text/JSON files are far more useful read inline than downloaded,
  // but there is no point streaming a multi-megabyte log into the panel.
  useEffect(() => {
    if (!entry || (entry.media !== 'json' && entry.media !== 'text') || entry.size > 256_000) return
    let cancelled = false
    fetch(localApiClient.fileContentUrl(entry.path), { credentials: 'include' })
      .then((res) => res.text())
      .then((body) => {
        if (cancelled) return
        setText(entry.media === 'json' ? safePrettyPrint(body) : body)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [entry])

  if (!entry) {
    return (
      <Panel title="Details">
        <p className="text-sm text-ink-faint">Select a file to preview it.</p>
      </Panel>
    )
  }

  const renderable = entry.media === 'image' || entry.media === 'fits'

  return (
    <Panel
      title="Details"
      actions={
        <a
          href={localApiClient.fileContentUrl(entry.path, true)}
          className="inline-flex items-center gap-1.5 border border-line px-3 py-1.5 text-xs tracking-wide text-ink-dim uppercase transition hover:border-amber-dim hover:text-ink"
        >
          <DownloadIcon size={14} />
          Download
        </a>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="font-mono text-xs break-all text-ink">{entry.path}</p>
        <div className="grid grid-cols-2 gap-3">
          <Readout label="Size" value={formatBytes(entry.size)} />
          <Readout label="Type" value={entry.media} />
          <Readout label="Modified" value={formatTimestamp(entry.modified_at)} />
        </div>

        {renderable ? (
          <img
            // FITS goes through the server-side renderer; a JPEG could be
            // shown directly, but routing both the same way keeps the
            // downscaling (and the memory cost) on the camera rather than
            // pushing a 12-megapixel file at the browser.
            src={localApiClient.filePreviewUrl(entry.path, 800)}
            alt={entry.name}
            className="w-full border border-line-soft bg-void"
          />
        ) : null}

        {text !== null ? (
          <pre className="max-h-80 overflow-auto border border-line-soft bg-void p-3 font-mono text-xs text-ink-dim">
            {text}
          </pre>
        ) : null}
      </div>
    </Panel>
  )
}

function safePrettyPrint(body: string): string {
  try {
    return JSON.stringify(JSON.parse(body), null, 2)
  } catch {
    return body
  }
}

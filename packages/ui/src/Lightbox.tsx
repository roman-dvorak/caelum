import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { ChevronLeftIcon, ChevronRightIcon, CloseIcon } from './icons.js'

export interface LightboxItem {
  src: string
  caption?: ReactNode
}

export interface LightboxProps {
  items: LightboxItem[]
  index: number
  onIndexChange: (index: number) => void
  onClose: () => void
}

/**
 * Fullscreen image viewer with prev/next navigation — a generic gallery
 * primitive with no caelum-specific knowledge (the caller supplies `src` +
 * an optional `caption`), so both the Recordings capture gallery and the
 * derivatives gallery can share one implementation.
 *
 * There is no other modal/overlay primitive anywhere in this codebase to
 * build on, so this owns its own fixed-position overlay and keyboard
 * handling — mirroring the one existing precedent for page-level keydown
 * handling, `AppShell`'s mobile nav drawer's Escape-to-close effect.
 */
export function Lightbox({ items, index, onIndexChange, onClose }: LightboxProps) {
  const item = items[index]

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
      else if (event.key === 'ArrowLeft') onIndexChange((index - 1 + items.length) % items.length)
      else if (event.key === 'ArrowRight') onIndexChange((index + 1) % items.length)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [index, items.length, onClose, onIndexChange])

  if (!item) return null

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-void/95 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div className="flex items-center justify-between px-4 py-3 font-mono text-xs text-ink-faint">
        <span className="tabular-nums">
          {index + 1} / {items.length}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="text-ink-dim hover:text-ink"
          aria-label="Close"
        >
          <CloseIcon size={22} />
        </button>
      </div>

      <div className="relative flex flex-1 items-center justify-center overflow-hidden px-4 pb-4">
        {items.length > 1 ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onIndexChange((index - 1 + items.length) % items.length)
            }}
            className="absolute left-2 text-ink-faint hover:text-ink sm:left-6"
            aria-label="Previous"
          >
            <ChevronLeftIcon size={32} />
          </button>
        ) : null}

        <img
          src={item.src}
          alt=""
          onClick={(e) => e.stopPropagation()}
          className="max-h-full max-w-full object-contain"
        />

        {items.length > 1 ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onIndexChange((index + 1) % items.length)
            }}
            className="absolute right-2 text-ink-faint hover:text-ink sm:right-6"
            aria-label="Next"
          >
            <ChevronRightIcon size={32} />
          </button>
        ) : null}
      </div>

      {item.caption ? (
        <div
          onClick={(e) => e.stopPropagation()}
          className="border-t border-line-soft px-4 py-3 font-mono text-xs text-ink-dim"
        >
          {item.caption}
        </div>
      ) : null}
    </div>
  )
}

import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { AstroMetersLogo } from './AstroMetersLogo.js'
import { BUILD_INFO, DEVELOPER_NAME, DEVELOPER_URL, DOCS_URL } from './brand.js'
import { BookIcon, CloseIcon, MenuIcon } from './icons.js'
import { ThemeToggle } from './theme.js'
import { buttonClass } from './buttonClass.js'
import { navItemClass } from './navigation.js'
import type { NavItem, NavSection } from './navigation.js'

export interface AppShellProps {
  sections: NavSection[]
  /** Renders one nav entry. Supplied by the app so this package stays free
   * of a react-router dependency — both apps use different route trees and
   * the shell has no business knowing about either. */
  renderNavItem: (item: NavItem, className: (isActive: boolean) => string) => ReactNode
  /** Small caption under the wordmark, e.g. the camera name. */
  subtitle?: string
  /** Account block above the footer — identity, sign out. */
  footer?: ReactNode
  children: ReactNode
}

/**
 * Sidebar application frame shared by local-web and remote-web.
 *
 * The sidebar is a permanent column from `lg` up and an overlay drawer below
 * it — a camera is as likely to be checked from a phone in the garden as
 * from a desk, and a permanently-docked 15rem column on a 390px screen
 * leaves nothing for the image.
 */
export function AppShell({
  sections,
  renderNavItem,
  subtitle,
  footer,
  children,
}: AppShellProps) {
  const [drawerOpen, setDrawerOpen] = useState(false)

  // Any navigation closes the drawer. Listening for hashchange rather than
  // threading a callback through `renderNavItem` keeps the shell agnostic
  // about the router — both apps use HashRouter.
  useEffect(() => {
    const close = () => setDrawerOpen(false)
    window.addEventListener('hashchange', close)
    return () => window.removeEventListener('hashchange', close)
  }, [])

  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDrawerOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawerOpen])

  return (
    <div className="min-h-svh lg:grid lg:grid-cols-[15rem_1fr]">
      {/* Mobile header — the only place the drawer can be opened from. */}
      <header className="sticky top-0 z-30 flex items-center gap-3 bg-navy px-3 py-2.5 shadow-md lg:hidden">
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="Open navigation"
          className="flex h-9 w-9 items-center justify-center rounded-md text-on-navy hover:bg-nebula"
        >
          <MenuIcon />
        </button>
        <Wordmark subtitle={subtitle} />
      </header>

      {drawerOpen ? (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setDrawerOpen(false)}
          className="fixed inset-0 z-40 bg-surface-0/70 backdrop-blur-sm lg:hidden"
        />
      ) : null}

      <aside
        className={[
          'flex w-60 flex-col border-r border-border bg-surface-200',
          'fixed inset-y-0 left-0 z-50 transition-transform duration-200 lg:sticky lg:top-0 lg:z-auto lg:h-svh lg:translate-x-0',
          drawerOpen ? 'translate-x-0' : '-translate-x-full',
        ].join(' ')}
      >
        <div className="flex items-center justify-between bg-navy px-4 py-3.5">
          <Wordmark subtitle={subtitle} />
          <button
            type="button"
            onClick={() => setDrawerOpen(false)}
            aria-label="Close navigation"
            className="rounded-md p-1 text-on-navy hover:bg-nebula lg:hidden"
          >
            <CloseIcon />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {sections.map((section, index) => (
            <div key={section.title ?? index} className={index > 0 ? 'mt-5' : undefined}>
              {section.title ? (
                <p className="px-3 pb-1.5 text-label-sm tracking-[0.08em] text-ink-muted uppercase">
                  {section.title}
                </p>
              ) : null}
              <div className="flex flex-col gap-0.5">
                {section.items.map((item) => renderNavItem(item, navItemClass))}
              </div>
            </div>
          ))}
        </nav>

        <div className="flex flex-col gap-2 border-t border-border-subtle p-3">
          {footer}
          <div className="flex gap-2">
            <div className="min-w-0 flex-1">
              <ThemeToggle />
            </div>
            <a
              href={DOCS_URL}
              target="_blank"
              rel="noreferrer noopener"
              title="Documentation"
              aria-label="Documentation"
              className={buttonClass('secondary', 'px-2.5')}
            >
              <BookIcon size={18} />
            </a>
          </div>
          <About />
        </div>
      </aside>

      <main className="min-w-0 px-4 py-5 sm:px-6 sm:py-6 lg:px-8">{children}</main>
    </div>
  )
}

/** What this is, which version and build, and who makes it. */
function About() {
  return (
    <div className="flex items-start gap-2.5 px-1 pt-1">
      <a href={DEVELOPER_URL} target="_blank" rel="noreferrer noopener" className="mt-0.5 shrink-0" title={DEVELOPER_NAME}>
        <AstroMetersLogo size={34} />
      </a>
      <div className="min-w-0 text-xs text-ink-muted">
        <p>
          <span className="font-display font-bold text-ink">caelum</span>{' '}
          <span className="font-mono text-code-sm">{BUILD_INFO.version}</span>
        </p>
        <p>Allsky camera software</p>
        <p className="font-mono text-code-sm break-all">build {BUILD_INFO.build}</p>
        <p>
          by{' '}
          <a href={DEVELOPER_URL} target="_blank" rel="noreferrer noopener" className="text-sky hover:underline">
            {DEVELOPER_NAME}
          </a>
        </p>
      </div>
    </div>
  )
}

function Wordmark({ subtitle }: { subtitle?: string }) {
  return (
    <span className="flex min-w-0 items-center gap-2.5 text-on-navy">
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber shadow-glow-amber" />
      <span className="flex min-w-0 flex-col">
        <span className="font-display text-display-sm font-bold leading-tight tracking-[-0.03em]">caelum</span>
        {subtitle ? <span className="truncate text-xs opacity-75">{subtitle}</span> : null}
      </span>
    </span>
  )
}

/** Page heading used by every page, so they all sit on the same baseline. */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="font-display text-display-lg text-ink">{title}</h1>
        {description ? <p className="mt-1.5 max-w-2xl text-sm text-ink-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}

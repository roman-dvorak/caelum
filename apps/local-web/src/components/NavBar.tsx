import { NavLink } from 'react-router-dom'

const LINKS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/live', label: 'Live stream' },
  { to: '/settings', label: 'Settings' },
  { to: '/plugins', label: 'Plugins' },
]

export function NavBar() {
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-void/95 backdrop-blur-sm">
      <div className="mx-auto flex w-full max-w-5xl items-center gap-1 px-4">
        <span className="mr-6 flex items-center gap-2 py-3.5 text-sm font-semibold tracking-[0.2em] text-ink uppercase">
          <span className="h-1.5 w-1.5 rounded-full bg-amber shadow-[0_0_8px_var(--color-amber)]" />
          caelum
        </span>
        <nav className="flex gap-1">
          {LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) =>
                [
                  'border-b-2 px-3 py-3.5 text-xs font-medium tracking-widest uppercase transition',
                  isActive
                    ? 'border-amber text-amber'
                    : 'border-transparent text-ink-dim hover:border-line hover:text-ink',
                ].join(' ')
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </header>
  )
}

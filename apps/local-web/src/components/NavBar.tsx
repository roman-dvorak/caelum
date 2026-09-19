import { NavLink } from 'react-router-dom'

const LINKS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/live', label: 'Live stream' },
  { to: '/settings', label: 'Settings' },
  { to: '/plugins', label: 'Plugins' },
]

export function NavBar() {
  return (
    <header className="sticky top-0 z-10 flex items-center gap-1 border-b border-slate-800 bg-slate-950/90 px-4 py-3 backdrop-blur-sm">
      <span className="mr-4 font-semibold tracking-wide text-slate-100">caelum</span>
      <nav className="flex gap-1">
        {LINKS.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.end}
            className={({ isActive }) =>
              [
                'rounded-md px-3 py-1.5 text-sm font-medium transition',
                isActive ? 'bg-slate-800 text-slate-100' : 'text-slate-400 hover:text-slate-200',
              ].join(' ')
            }
          >
            {link.label}
          </NavLink>
        ))}
      </nav>
    </header>
  )
}

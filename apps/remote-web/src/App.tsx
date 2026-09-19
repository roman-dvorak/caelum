import { HashRouter, NavLink, Route, Routes } from 'react-router-dom'
import { AppShell, CameraIcon, ImagesIcon } from '@caelum/ui'
import type { NavItem, NavSection } from '@caelum/ui'
import { useCameras } from './hooks/useCameras.ts'
import { CameraList } from './pages/CameraList.tsx'
import { CameraDetail } from './pages/CameraDetail.tsx'

// Where the public documentation is published. Unlike local-web, which
// reads this from the backend config, this app has no backend at all — it
// is static files on an Apache host — so it comes from the build env.
const DOCS_URL = import.meta.env.VITE_DOCS_URL || 'https://caelum.astrometers.eu'

// This app is deployed as static files on an Apache host with zero backend
// logic — there is no server-side rewrite to fall back arbitrary paths to
// index.html, so client-side routes must stay under the single "/"
// document. HashRouter keeps every route addressable without any Apache
// configuration at all.
export default function App() {
  return (
    <HashRouter>
      <Shell />
    </HashRouter>
  )
}

function Shell() {
  const { cameras } = useCameras()

  // Every published camera gets its own sidebar entry, so switching between
  // them is one click rather than a trip back through the index — this site
  // exists to compare several cameras, not to browse one.
  const sections: NavSection[] = [
    { items: [{ to: '/', label: 'All cameras', icon: ImagesIcon, end: true }] },
    ...(cameras && cameras.cameras.length > 0
      ? [
          {
            title: 'Cameras',
            items: cameras.cameras.map((camera) => ({
              to: `/camera/${camera.slug}`,
              label: camera.name,
              icon: CameraIcon,
            })),
          },
        ]
      : []),
  ]

  return (
    <AppShell
      sections={sections}
      subtitle="allsky network"
      docsUrl={DOCS_URL}
      renderNavItem={renderNavItem}
    >
      <Routes>
        <Route path="/" element={<CameraList />} />
        <Route path="/camera/:slug" element={<CameraDetail />} />
      </Routes>
    </AppShell>
  )
}

function renderNavItem(item: NavItem, className: (isActive: boolean) => string) {
  const Icon = item.icon
  return (
    <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => className(isActive)}>
      <Icon size={17} />
      <span className="truncate">{item.label}</span>
    </NavLink>
  )
}

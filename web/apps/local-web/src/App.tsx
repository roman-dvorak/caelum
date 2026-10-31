import { Suspense, lazy, useEffect } from 'react'
import { HashRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import {
  AppShell,
  Button,
  CpuIcon,
  DropletIcon,
  FolderIcon,
  GaugeIcon,
  ImagesIcon,
  LayersIcon,
  LensIcon,
  LiveIcon,
  Loading,
  LogoutIcon,
  LogsIcon,
  ProgramIcon,
  Message,
  PuzzleIcon,
  SlidersIcon,
  TerminalIcon,
  UsersIcon,
} from '@caelum/ui'
import type { NavItem, NavSection } from '@caelum/ui'
import { useAuth } from './authContext.ts'
import { PageErrorBoundary } from './components/PageErrorBoundary.tsx'
import { Dashboard } from './pages/Dashboard.tsx'
import { Files } from './pages/Files.tsx'
import { Frames } from './pages/Frames.tsx'
import { LiveStream } from './pages/LiveStream.tsx'
import { Login } from './pages/Login.tsx'
import { Logs } from './pages/Logs.tsx'
import { Plugins } from './pages/Plugins.tsx'
import { System } from './pages/System.tsx'
import { Users } from './pages/Users.tsx'

// xterm.js and json-edit-react are together most of this app's JavaScript,
// and both belong to admin-only pages that a given session may never open.
// Splitting them out keeps the first load small — which matters when the
// camera is serving the bundle itself over the local network.
const Settings = lazy(() => import('./pages/Settings.tsx').then((m) => ({ default: m.Settings })))
const TerminalPage = lazy(() =>
  import('./pages/Terminal.tsx').then((m) => ({ default: m.TerminalPage })),
)
const OverlayEditor = lazy(() =>
  import('./pages/OverlayEditor.tsx').then((m) => ({ default: m.OverlayEditor })),
)
const CapturePrograms = lazy(() =>
  import('./pages/CapturePrograms.tsx').then((m) => ({ default: m.CapturePrograms })),
)
const LensCalibration = lazy(() =>
  import('./pages/LensCalibration.tsx').then((m) => ({ default: m.LensCalibration })),
)
const WhiteBalance = lazy(() =>
  import('./pages/WhiteBalance.tsx').then((m) => ({ default: m.WhiteBalance })),
)

const VIEW_SECTION: NavSection = {
  title: 'Observe',
  items: [
    { to: '/', label: 'Dashboard', icon: GaugeIcon, end: true },
    { to: '/live', label: 'Live stream', icon: LiveIcon },
    { to: '/frames', label: 'Recordings', icon: ImagesIcon },
    { to: '/files', label: 'Files', icon: FolderIcon },
  ],
}

const ADMIN_SECTION: NavSection = {
  title: 'Manage',
  items: [
    { to: '/settings', label: 'Settings', icon: SlidersIcon },
    { to: '/programs', label: 'Capture programs', icon: ProgramIcon },
    { to: '/plugins', label: 'Plugins', icon: PuzzleIcon },
    { to: '/overlay', label: 'Overlay', icon: LayersIcon },
    { to: '/lens', label: 'Lens', icon: LensIcon },
    { to: '/white-balance', label: 'White balance', icon: DropletIcon },
    { to: '/terminal', label: 'Terminal', icon: TerminalIcon },
    { to: '/logs', label: 'Logs', icon: LogsIcon },
    { to: '/system', label: 'System', icon: CpuIcon },
    { to: '/users', label: 'Accounts', icon: UsersIcon },
  ],
}

// caelum's FastAPI backend serves this build as plain static files with no
// SPA-fallback rewrite rule (see caelum/src/caelum/api/app.py — a bare
// StaticFiles(html=True) mount), so client-side routes must not depend on
// the server rewriting arbitrary paths to index.html. HashRouter keeps
// every route at the single "/" document path.
export default function App() {
  const { context, loading, error, isAuthenticated, isAdmin, logout } = useAuth()
  const cameraName = context?.camera_name || ''

  // Tab titles are how you tell several cameras apart in a browser.
  useEffect(() => {
    document.title = cameraName ? `${cameraName} · caelum` : 'caelum'
  }, [cameraName])

  if (loading) {
    return (
      <div className="flex min-h-svh items-center justify-center">
        <Loading label="Connecting to caelum…" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex min-h-svh items-center justify-center p-4">
        <div className="max-w-md">
          <Message kind="error">Cannot reach the caelum backend: {error}</Message>
        </div>
      </div>
    )
  }

  // Anonymous callers get the login form, unless the operator has opened the
  // preview to the public — in which case they get the read-only shell and
  // can sign in later for control.
  const previewIsPublic = context?.preview_access === 'public'
  if (!isAuthenticated && !previewIsPublic) {
    return <Login />
  }

  const sections = isAdmin ? [VIEW_SECTION, ADMIN_SECTION] : [VIEW_SECTION]

  return (
    <HashRouter>
      <AppShell
        sections={sections}
        subtitle={[cameraName, isAdmin ? '' : 'view only'].filter(Boolean).join(' · ') || undefined}
        renderNavItem={renderNavItem}
        footer={
          <div className="flex flex-col gap-2">
            <div className="px-0.5 text-xs text-ink-muted">
              {isAuthenticated ? (
                <>
                  Signed in as <span className="text-ink-muted">{context?.username}</span>
                  <span className="text-ink-muted"> · {context?.role}</span>
                </>
              ) : (
                'Public preview'
              )}
            </div>
            {isAuthenticated && context?.auth_enabled ? (
              <Button icon={<LogoutIcon size={16} />} onClick={() => void logout()} className="w-full">
                Sign out
              </Button>
            ) : null}
          </div>
        }
      >
        <PageErrorBoundary>
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/live" element={<LiveStream />} />
              <Route path="/frames" element={<Frames />} />
              <Route path="/files" element={<Files />} />
              {/* Admin routes are not merely hidden from the sidebar — a viewer
                  who types the URL lands back on the dashboard, and the backend
                  would refuse the requests regardless. */}
              <Route path="/settings" element={isAdmin ? <Settings /> : <Navigate to="/" replace />} />
              <Route
                path="/programs"
                element={isAdmin ? <CapturePrograms /> : <Navigate to="/" replace />}
              />
              <Route path="/plugins" element={isAdmin ? <Plugins /> : <Navigate to="/" replace />} />
              <Route
                path="/overlay"
                element={isAdmin ? <OverlayEditor /> : <Navigate to="/" replace />}
              />
              <Route
                path="/white-balance"
                element={isAdmin ? <WhiteBalance /> : <Navigate to="/" replace />}
              />
              <Route path="/lens" element={isAdmin ? <LensCalibration /> : <Navigate to="/" replace />} />
              <Route
                path="/terminal"
                element={isAdmin ? <TerminalPage /> : <Navigate to="/" replace />}
              />
              <Route path="/logs" element={isAdmin ? <Logs /> : <Navigate to="/" replace />} />
              <Route path="/system" element={isAdmin ? <System /> : <Navigate to="/" replace />} />
              <Route path="/users" element={isAdmin ? <Users /> : <Navigate to="/" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </PageErrorBoundary>
      </AppShell>
    </HashRouter>
  )
}

function renderNavItem(item: NavItem, className: (isActive: boolean) => string) {
  const Icon = item.icon
  return (
    <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => className(isActive)}>
      <Icon size={17} />
      {item.label}
    </NavLink>
  )
}

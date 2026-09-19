import { HashRouter, Route, Routes } from 'react-router-dom'
import { NavBar } from './components/NavBar.tsx'
import { Dashboard } from './pages/Dashboard.tsx'
import { LiveStream } from './pages/LiveStream.tsx'
import { Settings } from './pages/Settings.tsx'
import { Plugins } from './pages/Plugins.tsx'

// caelum's FastAPI backend serves this build as plain static files with no
// SPA-fallback rewrite rule (see caelum/src/caelum/api/app.py — a bare
// StaticFiles(html=True) mount), so client-side routes must not depend on
// the server rewriting arbitrary paths to index.html. HashRouter keeps
// every route at the single "/" document path.
export default function App() {
  return (
    <HashRouter>
      <div className="flex min-h-svh flex-col">
        <NavBar />
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/live" element={<LiveStream />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/plugins" element={<Plugins />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  )
}

import { HashRouter, Link, Route, Routes } from 'react-router-dom'
import { CameraList } from './pages/CameraList.tsx'
import { CameraDetail } from './pages/CameraDetail.tsx'

// This app is deployed as static files on an Apache host with zero backend
// logic — there is no server-side rewrite to fall back arbitrary paths to
// index.html, so client-side routes must stay under the single "/"
// document. HashRouter keeps every route addressable without any Apache
// configuration at all.
export default function App() {
  return (
    <HashRouter>
      <div className="flex min-h-svh flex-col">
        <header className="sticky top-0 z-10 border-b border-line bg-void/95 backdrop-blur-sm">
          <div className="mx-auto flex w-full max-w-6xl items-center px-4 py-3.5">
            <Link
              to="/"
              className="flex items-center gap-2 text-sm font-semibold tracking-[0.2em] text-ink uppercase"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-amber shadow-[0_0_8px_var(--color-amber)]" />
              caelum <span className="font-normal tracking-normal text-ink-faint normal-case">/ allsky network</span>
            </Link>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
          <Routes>
            <Route path="/" element={<CameraList />} />
            <Route path="/camera/:slug" element={<CameraDetail />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  )
}

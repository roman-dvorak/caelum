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
        <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/90 px-4 py-3 backdrop-blur-sm">
          <Link to="/" className="font-semibold tracking-wide text-slate-100">
            caelum · allsky cameras
          </Link>
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

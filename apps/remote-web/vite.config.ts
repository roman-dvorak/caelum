import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// remote-web only ever talks to static JSON/JPEG files rsynced onto an
// Apache host (see VITE_REMOTE_BASE_URL in src/services/client.ts) — there
// is no backend to proxy to, dev or prod.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Relative asset URLs, so the build works unchanged whether it lands at
  // the web root or in some `/allsky/` subdirectory — the operator rsyncs
  // the folder wherever it suits them and nothing needs rebuilding. Safe
  // here specifically because the app uses HashRouter: every route lives
  // under the one index.html, so relative paths always resolve from it.
  base: './',
})

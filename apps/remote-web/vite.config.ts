import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// remote-web only ever talks to static JSON/JPEG files rsynced onto an
// Apache host (see VITE_REMOTE_BASE_URL in src/services/client.ts) — there
// is no backend to proxy to, dev or prod.
export default defineConfig({
  plugins: [react(), tailwindcss()],
})

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { buildInfoDefines } from '../../build-info.ts'

// caelum's default bind address (see caelum/src/caelum/settings.py:
// CAELUM_HTTP_PORT defaults to 8000). Override for a dev caelum instance
// running elsewhere, e.g. a Pi on the LAN: CAELUM_BACKEND_URL=http://raspberrypi.local:8000
const BACKEND = process.env.CAELUM_BACKEND_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: buildInfoDefines(),
  server: {
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
      },
      '/ws': {
        target: BACKEND,
        changeOrigin: true,
        ws: true,
      },
    },
  },
})

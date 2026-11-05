import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend runs on 8001 so it can sit alongside other local apps on 8000; override with API_PORT.
const apiPort = process.env.API_PORT ?? '8001'
// The web app is pinned to 5174 (5173 belongs to another local app); strictPort fails loudly instead of drifting,
// so the links in confirmation and reset emails always match. Override with WEB_PORT (and APP_URL on the backend).
const webPort = Number(process.env.WEB_PORT ?? '5174')

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: webPort,
    strictPort: true,
    proxy: { '/api': `http://localhost:${apiPort}` },
  },
})

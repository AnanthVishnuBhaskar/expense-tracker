import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend runs on 8001 so it can sit alongside other local apps on 8000; override with API_PORT.
const apiPort = process.env.API_PORT ?? '8001'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { '/api': `http://localhost:${apiPort}` },
  },
})

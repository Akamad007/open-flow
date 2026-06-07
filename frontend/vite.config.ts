import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxy target for /api + /storage. Defaults to the local backend (start_all.sh
// on :8002); in Docker it's set to http://backend:8000 via VITE_API_PROXY.
const apiTarget = process.env.VITE_API_PROXY || 'http://localhost:8002'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/storage': { target: apiTarget, changeOrigin: true },
    },
  },
})

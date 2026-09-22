import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The PWA talks to Django on the same origin. `npm run dev` proxies API and
// media requests to the Django development server; in production Caddy serves
// the built app next to the API, so no proxy is involved.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8081',
      '/media': 'http://localhost:8081',
    },
  },
})

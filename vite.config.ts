import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// The PWA talks to Django on the same origin. `npm run dev` proxies API and
// media requests to the Django development server; in production Caddy serves
// the built app next to the API, so no proxy is involved.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiURL = String(env.VITE_API_URL ?? process.env.VITE_API_URL ?? '').trim()

  // A production build that hard-codes localhost makes every shop device call
  // itself, so the catalogue never syncs. Dev builds are fine because the Vite
  // server proxies /api and /media; deployed builds must use the same origin.
  if (
    mode === 'production' &&
    /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?\/?$/i.test(apiURL)
  ) {
    throw new Error(
      `VITE_API_URL=${apiURL} points at localhost. Unset it for a production build: ` +
        'the dev server proxies /api and /media, and deployed builds call the API on the same origin.',
    )
  }

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': 'http://localhost:8081',
        '/media': 'http://localhost:8081',
      },
    },
  }
})

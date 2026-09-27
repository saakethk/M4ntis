import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { apiProxy, backendProxyTarget, readListenPort } from './devProxy.ts'

// Vite rewrites import.meta.dirname to this config file's directory.
declare global {
  interface ImportMeta {
    dirname: string
  }
}

// Repo-root .env (same file as .env.example), two levels above this app.
const repoRoot = `${import.meta.dirname}/../..`

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repoRoot, '')
  const target = backendProxyTarget(env)
  const port = readListenPort(env.FRONTEND_PORT, 8002, 'FRONTEND_PORT')
  return {
    plugins: [react()],
    envDir: repoRoot,
    server: {
      host: '0.0.0.0',
      port,
      strictPort: true,
      // Same-origin /auth and /strategies so the session cookie is first-party.
      proxy: apiProxy(target),
    },
    preview: {
      host: '0.0.0.0',
      port,
      strictPort: true,
      proxy: apiProxy(target),
    },
  }
})

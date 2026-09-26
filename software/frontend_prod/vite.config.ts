import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// Vite rewrites import.meta.dirname to this config file's directory.
declare global {
  interface ImportMeta {
    dirname: string
  }
}

// Repo-root .env (same file as .env.example), two levels above this app.
const repoRoot = `${import.meta.dirname}/../..`

function readFrontendPort(raw: string | undefined): number {
  const text = raw?.trim() ?? ''
  if (text === '') return 8002
  if (!/^\d+$/.test(text)) {
    throw new Error(`FRONTEND_PORT must be an integer from 1 to 65535, got ${JSON.stringify(raw)}`)
  }
  const port = Number(text)
  if (port < 1 || port > 65535) {
    throw new Error(`FRONTEND_PORT must be an integer from 1 to 65535, got ${port}`)
  }
  return port
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repoRoot, '')
  return {
    plugins: [react()],
    envDir: repoRoot,
    server: {
      host: '0.0.0.0',
      port: readFrontendPort(env.FRONTEND_PORT),
      strictPort: true,
    },
  }
})

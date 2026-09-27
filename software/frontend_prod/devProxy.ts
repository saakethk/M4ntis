// Local API proxy for the Vite dev server. The browser must call the API on
// the same site as the page, or a SameSite=Lax session cookie is dropped.

export const API_PREFIXES = [
  '/auth',
  '/strategies',
  '/symbols',
  '/backtests',
  '/discussions',
  '/llm',
  '/health',
] as const

export type ApiProxyEntry = {
  target: string
  changeOrigin: boolean
}

export function readListenPort(raw: string | undefined, fallback: number, name: string): number {
  const text = raw?.trim() ?? ''
  if (text === '') return fallback
  if (!/^\d+$/.test(text)) {
    throw new Error(`${name} must be an integer from 1 to 65535, got ${JSON.stringify(raw)}`)
  }
  const port = Number(text)
  if (port < 1 || port > 65535) {
    throw new Error(`${name} must be an integer from 1 to 65535, got ${port}`)
  }
  return port
}

// Prefer VITE_API_URL when it is a real origin. Loopback names are rewritten
// to 127.0.0.1 so the dev server reaches a backend bound on IPv4.
export function backendProxyTarget(env: { BACKEND_PORT?: string; VITE_API_URL?: string }): string {
  const raw = env.VITE_API_URL?.trim() ?? ''
  if (raw) {
    try {
      const url = new URL(raw)
      if (url.protocol === 'http:' || url.protocol === 'https:') {
        if (url.hostname === '0.0.0.0' || url.hostname === 'localhost' || url.hostname === '::1') {
          url.hostname = '127.0.0.1'
        }
        return url.origin
      }
    } catch {
      // Fall through to BACKEND_PORT.
    }
  }
  const port = readListenPort(env.BACKEND_PORT, 8001, 'BACKEND_PORT')
  return `http://127.0.0.1:${port}`
}

export function apiProxy(target: string): Record<string, ApiProxyEntry> {
  return Object.fromEntries(
    API_PREFIXES.map((prefix) => [prefix, { target, changeOrigin: true }]),
  )
}

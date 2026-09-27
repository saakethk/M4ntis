// Where the browser should send API requests.
//
// During `vite` dev, the base is empty so fetches stay on the page origin
// (localhost, 127.0.0.1, or 0.0.0.0). The dev server proxies those paths to
// the backend. A page on http://0.0.0.0:8002 calling http://localhost:8001 is
// cross-site, and the browser will not store or send the SameSite=Lax session
// cookie.
//
// A production build uses VITE_API_URL when it names a real host. If that URL
// is still a local bind address, it is rewritten to the page host so the
// cookie and the request share one site. The port stays the API port.

const DEFAULT_API_BASE = 'http://localhost:8001'
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '0.0.0.0', '::1'])

export type ApiBaseOptions = {
  dev?: boolean
  pageHostname?: string
}

export function resolveApiBase(value: string | undefined, options: ApiBaseOptions = {}): string {
  if (options.dev) return ''

  const pageHost = normalizeHost(options.pageHostname)
  const trimmed = value?.trim() ?? ''
  if (!trimmed) return alignToPage(DEFAULT_API_BASE, pageHost)

  let url: URL
  try {
    url = new URL(trimmed)
  } catch {
    return alignToPage(DEFAULT_API_BASE, pageHost)
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return alignToPage(DEFAULT_API_BASE, pageHost)
  }
  return alignToPage(formatBase(url), pageHost)
}

function alignToPage(base: string, pageHost: string): string {
  const url = new URL(base)
  const apiHost = normalizeHost(url.hostname)
  if (pageHost && LOCAL_HOSTS.has(pageHost) && LOCAL_HOSTS.has(apiHost) && pageHost !== apiHost) {
    url.hostname = pageHost
  } else if (!pageHost && apiHost === '0.0.0.0') {
    url.hostname = 'localhost'
  }
  return formatBase(url)
}

function formatBase(url: URL): string {
  const path = url.pathname.replace(/\/+$/, '')
  return `${url.origin}${path}`
}

function normalizeHost(host: string | undefined): string {
  return (host ?? '').trim().replace(/^\[|\]$/g, '').toLowerCase()
}

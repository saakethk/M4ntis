export type AppScreen =
  | { kind: 'home' }
  | { kind: 'discussions' }
  | { kind: 'new' }
  | { kind: 'edit'; id: number }
  | { kind: 'unavailable' }

function normalizePath(pathname: string): string {
  const withSlash = pathname.startsWith('/') ? pathname : `/${pathname}`
  if (withSlash.length > 1 && withSlash.endsWith('/')) return withSlash.slice(0, -1)
  return withSlash
}

function strategyId(segment: string): number | null {
  if (!/^[1-9]\d*$/.test(segment)) return null
  const id = Number(segment)
  if (!Number.isSafeInteger(id)) return null
  return id
}

// Portfolio is `/`. Discussions are `/discussions`. A saved strategy is
// `/strategy/:id`. A strategy that has not been saved yet is `/strategy/new`.
// Any other `/strategy/...` path is not a project we can open.
export function parseRoute(pathname: string): AppScreen {
  const path = normalizePath(pathname)
  if (path === '/' || path === '/strategy') return { kind: 'home' }
  if (path === '/discussions') return { kind: 'discussions' }
  if (path === '/strategy/new') return { kind: 'new' }
  if (path.startsWith('/strategy/')) {
    const id = strategyId(path.slice('/strategy/'.length))
    if (id != null) return { kind: 'edit', id }
    return { kind: 'unavailable' }
  }
  return { kind: 'home' }
}

export function routePath(screen: AppScreen): string | null {
  switch (screen.kind) {
    case 'home':
      return '/'
    case 'discussions':
      return '/discussions'
    case 'new':
      return '/strategy/new'
    case 'edit':
      return `/strategy/${screen.id}`
    case 'unavailable':
      return null
  }
}

// URL <-> screen mapping. The app uses the History API directly; there is no router library.
//
//   /                 portfolio
//   /discussions      discussions feed
//   /strategy/new     unsaved strategy
//   /strategy/:id     saved strategy
//   /backtest/:id     backtest report

export type AppScreen =
  | { kind: 'home' }
  | { kind: 'discussions' }
  | { kind: 'new' }
  | { kind: 'edit'; id: number }
  | { kind: 'backtest'; id: number }
  | { kind: 'unavailable' }

function positiveId(segment: string): number | null {
  if (!/^[1-9]\d*$/.test(segment)) return null
  const value = Number(segment)
  return Number.isSafeInteger(value) ? value : null
}

export function parseRoute(pathname: string): AppScreen {
  let path = pathname.startsWith('/') ? pathname : `/${pathname}`
  if (path.length > 1 && path.endsWith('/')) path = path.slice(0, -1)
  if (path === '/' || path === '/strategy') return { kind: 'home' }
  if (path === '/discussions') return { kind: 'discussions' }
  if (path === '/strategy/new') return { kind: 'new' }
  for (const [prefix, kind] of [['/backtest/', 'backtest'], ['/strategy/', 'edit']] as const) {
    if (path.startsWith(prefix)) {
      const value = positiveId(path.slice(prefix.length))
      return value == null ? { kind: 'unavailable' } : { kind, id: value }
    }
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
    case 'backtest':
      return `/backtest/${screen.id}`
    case 'unavailable':
      return null
  }
}

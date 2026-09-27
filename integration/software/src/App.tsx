import { useCallback, useEffect, useState } from 'react'
import { getMe, logout, type User } from './api/auth.ts'
import { Shell, type Section } from './components/Shell.tsx'
import { AuthCard } from './features/auth/AuthCard.tsx'
import { BacktestPage } from './features/backtest/BacktestPage.tsx'
import { Discussions } from './features/discussions/Discussions.tsx'
import { StrategyEditor } from './features/editor/StrategyEditor.tsx'
import { Portfolio } from './features/portfolio/Portfolio.tsx'
import type { LoadedStrategy } from './flow/serialize.ts'
import { parseRoute, routePath, type AppScreen } from './routes.ts'

const currentRoute = () => parseRoute(window.location.pathname)

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  const [sessionError, setSessionError] = useState<string | null>(null)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)
  const [screen, setScreen] = useState<AppScreen>(currentRoute)
  // A program imported from JSON on the portfolio page, opened in a new editor.
  const [imported, setImported] = useState<LoadedStrategy | null>(null)
  // Remounts the editor for each strategy opened, but not when a new one is first saved.
  const [editorSession, setEditorSession] = useState(0)

  useEffect(() => {
    const onPopState = () => setScreen(currentRoute())
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    let ignore = false
    getMe()
      .then((next) => !ignore && setUser(next))
      .catch((error: unknown) => !ignore && setSessionError(error instanceof Error ? error.message : 'Could not reach the server.'))
      .finally(() => !ignore && setReady(true))
    return () => {
      ignore = true
    }
  }, [])

  const go = useCallback((next: AppScreen, mode: 'push' | 'replace' = 'push') => {
    const path = routePath(next)
    if (path != null && path !== window.location.pathname) window.history[mode === 'replace' ? 'replaceState' : 'pushState'](null, '', path)
    setScreen(next)
  }, [])

  async function handleLogout() {
    setLoggingOut(true)
    setLogoutError(null)
    try {
      await logout()
      setUser(null)
      go({ kind: 'home' })
    } catch (error) {
      setLogoutError(error instanceof Error ? error.message : 'Could not sign out.')
    } finally {
      setLoggingOut(false)
    }
  }

  const openStrategy = (id: number) => {
    setEditorSession((n) => n + 1)
    go({ kind: 'edit', id })
  }
  const newStrategy = (program: LoadedStrategy | null = null) => {
    setImported(program)
    setEditorSession((n) => n + 1)
    go({ kind: 'new' })
  }
  const inEditor = user != null && (screen.kind === 'new' || screen.kind === 'edit' || screen.kind === 'unavailable')

  let main
  if (!ready) {
    main = (
      <div className="gate">
        <p className="status-line">Checking session…</p>
      </div>
    )
  } else if (!user) {
    main = (
      <div className="gate">
        <div className="gate-stack">
          {sessionError ? (
            <p className="form-error" role="alert">
              {sessionError}
            </p>
          ) : null}
          <AuthCard
            onSignedIn={(next) => {
              setSessionError(null)
              setUser(next)
            }}
          />
        </div>
      </div>
    )
  } else if (screen.kind === 'home') {
    main = <Portfolio onNew={() => newStrategy()} onEdit={openStrategy} onImport={newStrategy} onOpenBacktest={(id) => go({ kind: 'backtest', id })} />
  } else if (screen.kind === 'discussions') {
    main = <Discussions user={user} onOpenStrategy={openStrategy} />
  } else if (screen.kind === 'backtest') {
    main = <BacktestPage id={screen.id} onOpenStrategy={openStrategy} />
  } else {
    main = (
      <StrategyEditor
        key={editorSession}
        userId={user.id}
        strategyId={screen.kind === 'edit' ? screen.id : null}
        initialProgram={screen.kind === 'new' ? imported : null}
        unavailable={screen.kind === 'unavailable'}
        onClose={() => go({ kind: 'home' })}
        onCreated={(id) => go({ kind: 'edit', id }, 'replace')}
        onOpenBacktest={(id) => go({ kind: 'backtest', id })}
      />
    )
  }

  return (
    <Shell
      user={user}
      section={screen.kind === 'discussions' ? 'discussions' : 'strategies'}
      onNavigate={(section: Section) => go(section === 'discussions' ? { kind: 'discussions' } : { kind: 'home' })}
      onLogout={() => void handleLogout()}
      loggingOut={loggingOut}
      logoutError={logoutError}
      flush={inEditor}
    >
      {main}
    </Shell>
  )
}

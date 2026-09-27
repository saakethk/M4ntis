import { useEffect, useState } from 'react'
import { getMe, logout, type User } from './api'
import { AuthCard } from './components/AuthCard'
import { BacktestPage } from './components/BacktestPage'
import { Discussions } from './components/Discussions'
import { Portfolio } from './components/Portfolio'
import { Shell } from './components/Shell'
import { StrategyEditor } from './components/StrategyEditor'
import { parseRoute, routePath, type AppScreen } from './routes'

function currentRoute(): AppScreen {
  return parseRoute(window.location.pathname)
}

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  const [sessionError, setSessionError] = useState<string | null>(null)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)
  const [screen, setScreen] = useState<AppScreen>(currentRoute())

  useEffect(() => {
    function onPopState() {
      setScreen(currentRoute())
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  function go(next: AppScreen, mode: 'push' | 'replace' = 'push') {
    const path = routePath(next)
    if (path != null && path !== window.location.pathname) {
      if (mode === 'replace') window.history.replaceState(null, '', path)
      else window.history.pushState(null, '', path)
    }
    setScreen(next)
  }

  useEffect(() => {
    let ignore = false
    // getMe returns null on 401. A missing cookie is signed out, not an error.
    getMe()
      .then((next) => {
        if (ignore) return
        setUser(next)
        setSessionError(null)
      })
      .catch((error: unknown) => {
        if (ignore) return
        setUser(null)
        setSessionError(error instanceof Error ? error.message : 'Could not reach the server.')
      })
      .finally(() => {
        if (!ignore) setReady(true)
      })
    return () => {
      ignore = true
    }
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

  function openStrategy(id: string) {
    go(parseRoute(`/strategy/${id}`))
  }

  const editorOpen =
    user != null && (screen.kind === 'new' || screen.kind === 'edit' || screen.kind === 'unavailable')
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
    main = <Portfolio onNew={() => go({ kind: 'new' })} onEdit={openStrategy} />
  } else if (screen.kind === 'discussions') {
    main = <Discussions user={user} onOpenStrategy={openStrategy} />
  } else if (screen.kind === 'backtest') {
    main = <BacktestPage id={screen.id} onOpenStrategy={(strategyId) => go({ kind: 'edit', id: strategyId })} />
  } else {
    main = (
      <StrategyEditor
        userId={user.id}
        strategyId={screen.kind === 'edit' ? screen.id : null}
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
      onLogout={handleLogout}
      loggingOut={loggingOut}
      logoutError={logoutError}
      flush={editorOpen}
      page={screen.kind === 'discussions' ? 'discussions' : 'strategies'}
      onNavigate={
        user
          ? (next) => {
              if (next === 'discussions') setScreen({ kind: 'discussions' })
              else go({ kind: 'home' })
            }
          : undefined
      }
    >
      {main}
    </Shell>
  )
}

import { useEffect, useState } from 'react'
import { getMe, logout, type User } from './api'
import { AuthCard } from './components/AuthCard'
import { Discussions } from './components/Discussions'
import { Portfolio } from './components/Portfolio'
import { Shell } from './components/Shell'
import { StrategyEditor } from './components/StrategyEditor'

type Screen =
  | { kind: 'home' }
  | { kind: 'discussions' }
  | { kind: 'new' }
  | { kind: 'edit'; id: number }
  | { kind: 'unavailable' }

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  const [sessionError, setSessionError] = useState<string | null>(null)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)
  const [screen, setScreen] = useState<Screen>({ kind: 'home' })

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
      setScreen({ kind: 'home' })
    } catch (error) {
      setLogoutError(error instanceof Error ? error.message : 'Could not sign out.')
    } finally {
      setLoggingOut(false)
    }
  }

  function openStrategy(id: string) {
    if (/^\d+$/.test(id)) setScreen({ kind: 'edit', id: Number(id) })
    else setScreen({ kind: 'unavailable' })
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
    main = <Portfolio onNew={() => setScreen({ kind: 'new' })} onEdit={openStrategy} />
  } else if (screen.kind === 'discussions') {
    main = <Discussions onOpenStrategy={openStrategy} />
  } else {
    main = (
      <StrategyEditor
        userId={user.id}
        strategyId={screen.kind === 'edit' ? screen.id : null}
        unavailable={screen.kind === 'unavailable'}
        onClose={() => setScreen({ kind: 'home' })}
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
          ? (next) => setScreen(next === 'discussions' ? { kind: 'discussions' } : { kind: 'home' })
          : undefined
      }
    >
      {main}
    </Shell>
  )
}

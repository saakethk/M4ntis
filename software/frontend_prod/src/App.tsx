import { useEffect, useState } from 'react'
import { getMe, logout, type User } from './api'
import { AuthCard } from './components/AuthCard'
import { Portfolio } from './components/Portfolio'
import { Shell } from './components/Shell'

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  const [section, setSection] = useState<Section>('strategies')
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)

  useEffect(() => {
    let ignore = false
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
    } catch (error) {
      setLogoutError(error instanceof Error ? error.message : 'Could not sign out.')
    } finally {
      setLoggingOut(false)
    }
  }

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
  } else {
    main = <Portfolio />
  }

  return (
    <Shell user={user} onLogout={handleLogout} loggingOut={loggingOut} logoutError={logoutError}>
      {main}
    </Shell>
  )
}

import { useEffect, useState } from 'react'
import { getMe, logout, type User } from './api'
import { AuthCard } from './components/AuthCard'
import { Portfolio } from './components/Portfolio'
import { Shell, type Section } from './components/Shell'

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  const [sessionError, setSessionError] = useState<string | null>(null)
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
        setReady(true)
      })
      .catch((error: unknown) => {
        if (ignore) return
        setUser(null)
        setSessionError(error instanceof Error ? error.message : 'Could not reach the server.')
        setReady(true)
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
      setSection('strategies')
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
        <AuthCard onSignedIn={setUser} notice={sessionError} />
      </div>
    )
  } else if (section === 'account') {
    main = (
      <section className="account">
        <h1>Account</h1>
        <p className="subtitle">Signed in as {user.email}</p>
        {logoutError ? (
          <p className="form-error" role="alert">
            {logoutError}
          </p>
        ) : null}
        <button type="button" className="primary" onClick={handleLogout} disabled={loggingOut}>
          Sign out
        </button>
      </section>
    )
  } else {
    main = (
      <>
        {logoutError ? (
          <p className="form-error banner" role="alert">
            {logoutError}
          </p>
        ) : null}
        <Portfolio />
      </>
    )
  }

  return (
    <Shell user={user} section={user ? section : 'strategies'} onSection={setSection}>
      {main}
    </Shell>
  )
}

import { useState, type FormEvent } from 'react'
import { login, register, type User } from '../../api/auth.ts'

type Mode = 'signin' | 'register'

export function AuthCard({ onSignedIn }: { onSignedIn: (user: User) => void }) {
  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setPending(true)
    try {
      const user = mode === 'signin' ? await login(email, password) : await register(email, password)
      setPassword('')
      onSignedIn(user)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not reach the server.')
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="auth-card">
      <h1>Welcome to Mantis</h1>
      <p className="subtitle">Sign in to access your trading strategies</p>
      <div className="tabs" role="tablist" aria-label="Account">
        {(['signin', 'register'] as const).map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={mode === item}
            onClick={() => {
              setMode(item)
              setError(null)
            }}
          >
            {item === 'signin' ? 'Sign In' : 'Create Account'}
          </button>
        ))}
      </div>
      <form onSubmit={onSubmit}>
        <label>
          Email
          <input type="email" name="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Password
          <input
            type="password"
            name="password"
            autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
            minLength={mode === 'register' ? 8 : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {mode === 'register' ? <p className="field-hint">At least 8 characters.</p> : null}
        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}
        <button type="submit" className="primary" disabled={pending}>
          {pending ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Create account'}
        </button>
      </form>
    </section>
  )
}

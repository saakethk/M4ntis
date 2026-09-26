import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { User } from '../api'
import { DUMMY_BALANCE, displayName } from '../strategies'

type Props = {
  user: User | null
  onLogout: () => void
  loggingOut: boolean
  logoutError: string | null
  flush?: boolean
  children: ReactNode
}

function UserGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="12" cy="8" r="3.2" />
      <path d="M5.2 19.2c1.3-3 3.6-4.5 6.8-4.5s5.5 1.5 6.8 4.5" />
    </svg>
  )
}

export function Shell({ user, onLogout, loggingOut, logoutError, flush = false, children }: Props) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!user) setMenuOpen(false)
  }, [user])

  useEffect(() => {
    if (!menuOpen) return
    function onPointer(event: MouseEvent) {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden="true">
            M
          </span>
          <span className="word">M4ntis</span>
        </div>
        <div className="user-slot" ref={menuRef}>
          {user ? (
            <button
              type="button"
              className="user-btn"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-label="Account"
              onClick={() => setMenuOpen((open) => !open)}
            >
              <UserGlyph />
            </button>
          ) : (
            <span className="user-btn" aria-hidden="true">
              <UserGlyph />
            </span>
          )}
          {user && menuOpen ? (
            <div className="user-menu" role="menu">
              <p className="user-menu-name">{displayName(user.email)}</p>
              <p className="user-menu-email">{user.email}</p>
              <p className="user-menu-balance">{DUMMY_BALANCE}</p>
              {logoutError ? (
                <p className="form-error" role="alert">
                  {logoutError}
                </p>
              ) : null}
              <button
                type="button"
                className="user-menu-signout"
                role="menuitem"
                onClick={onLogout}
                disabled={loggingOut}
              >
                Sign out
              </button>
            </div>
          ) : null}
        </div>
      </header>
      <main className={flush ? 'content content-flush' : 'content'}>{children}</main>
    </div>
  )
}

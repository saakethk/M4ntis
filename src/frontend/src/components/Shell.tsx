import { useCallback, useRef, useState, type ReactNode } from 'react'
import type { User } from '../api/auth.ts'
import { displayName } from '../lib/format.ts'
import { nextTheme, themeLabel, useTheme } from '../lib/theme.ts'
import { MonitorIcon, MoonIcon, SunIcon, UserIcon } from './icons.tsx'
import { useDismiss } from './useDismiss.ts'

export type Section = 'strategies' | 'discussions'

type Props = {
  user: User | null
  section: Section
  onNavigate: (section: Section) => void
  onLogout: () => void
  loggingOut: boolean
  logoutError: string | null
  /** Full-bleed content (the editor) instead of the padded page. */
  flush?: boolean
  children: ReactNode
}

export function Shell({ user, section, onNavigate, onLogout, loggingOut, logoutError, flush = false, children }: Props) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const closeMenu = useCallback(() => setMenuOpen(false), [])
  useDismiss(menuRef, menuOpen, closeMenu)

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden="true">
            M
          </span>
          <span className="word">M4ntis</span>
        </div>
        {user ? (
          <nav className="top-nav" aria-label="Sections">
            {(['strategies', 'discussions'] as const).map((item) => (
              <button
                key={item}
                type="button"
                className={section === item ? 'nav-link active' : 'nav-link'}
                aria-current={section === item ? 'page' : undefined}
                onClick={() => onNavigate(item)}
              >
                {item === 'strategies' ? 'Strategies' : 'Discussions'}
              </button>
            ))}
          </nav>
        ) : null}
        <div className="topbar-end">
          <ThemeToggle />
          {user ? (
            <div className="user-slot" ref={menuRef}>
              <button
                type="button"
                className="user-btn"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                aria-label="Account"
                onClick={() => setMenuOpen((open) => !open)}
              >
                <UserIcon />
              </button>
              {menuOpen ? (
                <div className="user-menu" role="menu">
                  <p className="user-menu-name">{displayName(user.email)}</p>
                  <p className="user-menu-email">{user.email}</p>
                  {logoutError ? (
                    <p className="form-error" role="alert">
                      {logoutError}
                    </p>
                  ) : null}
                  <button type="button" className="user-menu-signout" role="menuitem" onClick={onLogout} disabled={loggingOut}>
                    {loggingOut ? 'Signing out…' : 'Sign out'}
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </header>
      <main className={flush ? 'content content-flush' : 'content'}>{children}</main>
    </div>
  )
}

function ThemeToggle() {
  const { choice, resolved, setTheme } = useTheme()
  const next = nextTheme(choice)
  const current = choice === 'system' ? `System (${resolved})` : themeLabel(choice)
  const label = `Theme: ${current}. Switch to ${themeLabel(next)}`
  const Icon = choice === 'light' ? SunIcon : choice === 'dark' ? MoonIcon : MonitorIcon
  return (
    <button type="button" className="theme-toggle" aria-label={label} title={label} onClick={() => setTheme(next)}>
      <Icon size={18} />
    </button>
  )
}

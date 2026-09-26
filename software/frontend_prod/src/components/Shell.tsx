import type { ReactNode } from 'react'
import type { User } from '../api'
import { DUMMY_BALANCE, displayName } from '../strategies'

export type Section = 'strategies' | 'account'

type Props = {
  user: User | null
  section: Section
  onSection: (section: Section) => void
  onLogout: () => void
  loggingOut: boolean
  children: ReactNode
}

export function Shell({ user, section, onSection, onLogout, loggingOut, children }: Props) {
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="mark" aria-hidden="true">
            M
          </span>
          <span className="word">Mantis</span>
        </div>
        <nav className="nav" aria-label="Primary">
          <button
            type="button"
            className={section === 'strategies' ? 'nav-item active' : 'nav-item'}
            onClick={() => onSection('strategies')}
          >
            Strategies
          </button>
          <button type="button" className="nav-item" aria-disabled="true">
            Backtest
          </button>
          <button type="button" className="nav-item" aria-disabled="true">
            FPGA
          </button>
          <button
            type="button"
            className={section === 'account' ? 'nav-item active' : 'nav-item'}
            aria-disabled={user ? undefined : 'true'}
            onClick={() => {
              if (user) onSection('account')
            }}
          >
            Account
          </button>
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          {user ? (
            <div className="session">
              <span className="session-name">{displayName(user.email)}</span>
              <span className="session-balance">{DUMMY_BALANCE}</span>
              <span className="status-dot" title="Online" aria-label="Online" />
              <button type="button" className="text-button" onClick={onLogout} disabled={loggingOut}>
                Sign out
              </button>
            </div>
          ) : null}
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  )
}

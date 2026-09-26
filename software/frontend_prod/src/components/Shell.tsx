import type { ReactNode, SVGProps } from 'react'
import type { User } from '../api'
import { DUMMY_BALANCE, displayName } from '../strategies'

export type Section = 'strategies' | 'account'

type Props = {
  user: User | null
  section: Section
  onSection: (section: Section) => void
  children: ReactNode
}

function Glyph(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    />
  )
}

function StrategiesIcon() {
  return (
    <Glyph>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.4" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.4" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.4" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.4" />
    </Glyph>
  )
}

function BacktestIcon() {
  return (
    <Glyph>
      <path d="M4 19V10" />
      <path d="M10 19V6" />
      <path d="M16 19v-6" />
      <path d="M3 19h18" />
    </Glyph>
  )
}

function FpgaIcon() {
  return (
    <Glyph>
      <rect x="7" y="7" width="10" height="10" rx="1.6" />
      <path d="M9 3.5v3.5M15 3.5v3.5M9 17v3.5M15 17v3.5M3.5 9H7M3.5 15H7M17 9h3.5M17 15h3.5" />
    </Glyph>
  )
}

function AccountIcon() {
  return (
    <Glyph>
      <circle cx="12" cy="8" r="3.1" />
      <path d="M5.5 19.2c1.4-2.8 3.5-4.2 6.5-4.2s5.1 1.4 6.5 4.2" />
    </Glyph>
  )
}

export function Shell({ user, section, onSection, children }: Props) {
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
            <StrategiesIcon />
            Strategies
          </button>
          <button type="button" className="nav-item" aria-disabled="true">
            <BacktestIcon />
            Backtest
          </button>
          <button type="button" className="nav-item" aria-disabled="true">
            <FpgaIcon />
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
            <AccountIcon />
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
            </div>
          ) : null}
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  )
}

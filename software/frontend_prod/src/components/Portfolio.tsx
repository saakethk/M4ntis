import { useEffect, useRef, useState } from 'react'
import { listStrategies, type StrategySummary } from '../api'
import {
  STRATEGIES,
  formatDrawdown,
  formatPct,
  type Strategy,
  type StrategyStatus,
} from '../strategies'

type StatusFilter = 'all' | StrategyStatus

const FILTERS: { id: StatusFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'active', label: 'Active' },
  { id: 'ready', label: 'Ready' },
  { id: 'backtesting', label: 'Backtesting' },
  { id: 'draft', label: 'Draft' },
]

const STATUS_LABEL: Record<StrategyStatus, string> = {
  active: 'Active',
  ready: 'Ready',
  backtesting: 'Backtesting',
  draft: 'Draft',
}

function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="11" cy="11" r="6.25" stroke="currentColor" strokeWidth="1.75" />
      <path d="M16 16.5 20 20.5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
    </svg>
  )
}

function Chevron() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 9.5 12 15.5 18 9.5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function PlayIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M3.2 1.8v8.4L10 6 3.2 1.8Z" fill="currentColor" />
    </svg>
  )
}

function PlusIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

function metricText(value: number | null, format: (value: number) => string): string {
  return value === null ? '–' : format(value)
}

function withDummyMetrics(row: StrategySummary, index: number): Strategy {
  const sample = STRATEGIES[index % STRATEGIES.length]
  return {
    id: String(row.id),
    name: row.name,
    status: sample.status,
    createdLabel: sample.createdLabel,
    returnPct: sample.returnPct,
    maxDrawdownPct: sample.maxDrawdownPct,
    lastBacktest: sample.lastBacktest,
  }
}

function StrategyCard({ strategy, onEdit }: { strategy: Strategy; onEdit: (id: string) => void }) {
  const returnClass =
    strategy.returnPct === null ? 'metric-value' : strategy.returnPct < 0 ? 'metric-value down' : 'metric-value up'

  return (
    <article className="card">
      <div className="card-head">
        <span className={`badge badge-${strategy.status}`}>{STATUS_LABEL[strategy.status]}</span>
        <button type="button" className="play" aria-label={`Run ${strategy.name}`}>
          <PlayIcon />
        </button>
      </div>
      <h2>{strategy.name}</h2>
      <p className="created">{strategy.createdLabel}</p>
      <div className="card-spacer" />
      <div className="metrics">
        <div className="metric">
          <p className="metric-label">Return</p>
          <p className={returnClass}>{metricText(strategy.returnPct, formatPct)}</p>
        </div>
        <div className="metric">
          <p className="metric-label">Max drawdown</p>
          <p className="metric-value">{metricText(strategy.maxDrawdownPct, formatDrawdown)}</p>
        </div>
      </div>
      <div className="backtest-row">
        <p className="metric-label">Last backtest</p>
        <p className="backtest-when">{strategy.lastBacktest}</p>
      </div>
      <div className="card-links">
        <button type="button" className="text-btn strong" onClick={() => onEdit(strategy.id)}>
          Edit
        </button>
        <button type="button" className="text-btn">
          View details
        </button>
      </div>
    </article>
  )
}

export function Portfolio({ onNew, onEdit }: { onNew: () => void; onEdit: (id: string) => void }) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [statusOpen, setStatusOpen] = useState(false)
  const [strategies, setStrategies] = useState<Strategy[] | null>(null)
  const statusRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let ignore = false
    listStrategies()
      .then((rows) => {
        if (!ignore) setStrategies(rows.map(withDummyMetrics))
      })
      .catch(() => {
        if (!ignore) setStrategies(STRATEGIES)
      })
    return () => {
      ignore = true
    }
  }, [])

  useEffect(() => {
    if (!statusOpen) return
    function onPointer(event: MouseEvent) {
      if (!statusRef.current?.contains(event.target as Node)) setStatusOpen(false)
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setStatusOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [statusOpen])

  const selected = FILTERS.find((item) => item.id === status) ?? FILTERS[0]
  const needle = query.trim().toLowerCase()
  const catalog = strategies ?? []
  const visible = catalog.filter((strategy) => {
    const matchesName = needle.length === 0 || strategy.name.toLowerCase().includes(needle)
    const matchesStatus = status === 'all' || strategy.status === status
    return matchesName && matchesStatus
  })

  return (
    <section className="portfolio">
      <div className="page-head">
        <div>
          <h1>My Strategies</h1>
          <p className="subtitle">Manage, test, and deploy automated trading models.</p>
        </div>
        <button type="button" className="primary" onClick={onNew}>
          + New Strategy
        </button>
      </div>
      <div className="toolbar">
        <label className="search">
          <SearchIcon />
          <input
            type="search"
            placeholder="Search by name..."
            aria-label="Search by name"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <div className="status-filter" ref={statusRef}>
          <button
            type="button"
            className="status-btn"
            aria-haspopup="listbox"
            aria-expanded={statusOpen}
            onClick={() => setStatusOpen((open) => !open)}
          >
            Status: {selected.label}
            <Chevron />
          </button>
          {statusOpen ? (
            <ul className="status-menu" role="listbox" aria-label="Status">
              {FILTERS.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={item.id === status}
                    onClick={() => {
                      setStatus(item.id)
                      setStatusOpen(false)
                    }}
                  >
                    {item.label}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
      <div className="cards">
        {strategies === null ? <p className="empty">Loading strategies…</p> : null}
        {visible.map((strategy) => (
          <StrategyCard key={strategy.id} strategy={strategy} onEdit={onEdit} />
        ))}
        {strategies !== null && visible.length === 0 ? (
          <p className="empty">{catalog.length === 0 ? 'No strategies yet.' : 'No strategies match.'}</p>
        ) : null}
        <button type="button" className="add-card" onClick={onNew}>
          <PlusIcon />
          <span className="add-title">Add new strategy</span>
          <span className="add-copy">
            Create another project card and keep your portfolio organized in a clean grid.
          </span>
        </button>
      </div>
    </section>
  )
}

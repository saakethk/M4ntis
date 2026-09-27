import { useEffect, useState } from 'react'
import { getStrategy, listStrategies, type BacktestSummary, type StrategySummary } from '../../api/strategies.ts'
import { PlusIcon, SearchIcon, UploadIcon, DownloadIcon } from '../../components/icons.tsx'
import { fromDocument } from '../../flow/serialize.ts'
import { parseProgramFile, programFileName, programFileText } from '../../flow/programFile.ts'
import type { LoadedStrategy } from '../../flow/serialize.ts'
import { downloadText, pickTextFile } from '../../lib/files.ts'
import { pct, relativeTime, signedPct } from '../../lib/format.ts'
import { filterStrategies, portfolioView, type VisibilityFilter } from './portfolio.ts'

type Props = {
  onNew: () => void
  onEdit: (id: number) => void
  onImport: (program: LoadedStrategy) => void
  onOpenBacktest: (id: number) => void
}

const FILTERS: { id: VisibilityFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'private', label: 'Private' },
  { id: 'public', label: 'Public' },
]

export function Portfolio({ onNew, onEdit, onImport, onOpenBacktest }: Props) {
  const [rows, setRows] = useState<StrategySummary[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [visibility, setVisibility] = useState<VisibilityFilter>('all')

  useEffect(() => {
    let ignore = false
    listStrategies()
      .then((next) => !ignore && setRows(next))
      .catch((error: unknown) => {
        if (ignore) return
        setRows([])
        setLoadError(error instanceof Error ? error.message : 'Could not load strategies.')
      })
    return () => {
      ignore = true
    }
  }, [])

  async function importFile() {
    setNotice(null)
    try {
      const file = await pickTextFile()
      if (file) onImport(parseProgramFile(file.text))
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not read that file.')
    }
  }

  async function exportStrategy(row: StrategySummary) {
    setNotice(null)
    try {
      const program = fromDocument((await getStrategy(row.id)).document)
      downloadText(programFileName(row.name), programFileText(row.name, program.nodes, program.edges))
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not export that strategy.')
    }
  }

  const all = rows ?? []
  const view = portfolioView({ loading: rows === null, failed: loadError != null, count: all.length })
  const visible = filterStrategies(all, query, visibility)

  return (
    <section className="portfolio">
      <div className="page-head">
        <div>
          <h1>My Strategies</h1>
          <p className="subtitle">Build, test, and share automated trading strategies.</p>
        </div>
        <div className="page-actions">
          <button type="button" className="quiet with-icon" onClick={() => void importFile()}>
            <UploadIcon />
            Import JSON
          </button>
          {view !== 'get-started' ? (
            <button type="button" className="primary" onClick={onNew}>
              + New Strategy
            </button>
          ) : null}
        </div>
      </div>
      {notice ? (
        <p className="form-error" role="alert">
          {notice}
        </p>
      ) : null}

      {view === 'list' ? (
        <div className="toolbar">
          <label className="search">
            <SearchIcon />
            <input type="search" placeholder="Search by name..." aria-label="Search by name" value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <div className="segmented" role="radiogroup" aria-label="Visibility">
            {FILTERS.map((item) => (
              <button key={item.id} type="button" role="radio" aria-checked={visibility === item.id} onClick={() => setVisibility(item.id)}>
                {item.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="cards">
        {view === 'loading' ? <p className="empty">Loading strategies…</p> : null}
        {view === 'error' ? (
          <p className="empty" role="alert">
            {loadError}
          </p>
        ) : null}
        {view === 'get-started' ? (
          <button type="button" className="get-started" onClick={onNew}>
            <span className="get-started-title">Get Started</span>
            <span className="get-started-copy">Create a strategy from a template or a blank canvas, or import a JSON program.</span>
          </button>
        ) : null}
        {view === 'list'
          ? visible.map((row) => (
              <article className="card" key={row.id}>
                <div className="card-head">
                  <span className={`badge badge-${row.visibility}`}>{row.visibility === 'public' ? 'Public' : 'Private'}</span>
                  <button type="button" className="icon-button quiet" aria-label={`Download ${row.name} as JSON`} title="Download JSON" onClick={() => void exportStrategy(row)}>
                    <DownloadIcon />
                  </button>
                </div>
                <h2>{row.name}</h2>
                <p className="created">{row.updatedAt ? `Updated ${relativeTime(row.updatedAt)}` : 'Saved strategy'}</p>
                <LastBacktest summary={row.lastBacktest} onOpen={onOpenBacktest} />
                <button type="button" className="card-open" onClick={() => onEdit(row.id)}>
                  Open editor
                </button>
              </article>
            ))
          : null}
        {view === 'list' && visible.length === 0 ? <p className="empty">No strategies match.</p> : null}
        {view === 'list' ? (
          <button type="button" className="add-card" onClick={onNew}>
            <PlusIcon size={22} />
            <span className="add-title">New strategy</span>
          </button>
        ) : null}
      </div>
    </section>
  )
}

function LastBacktest({ summary, onOpen }: { summary: BacktestSummary | null; onOpen: (id: number) => void }) {
  const returnPct = summary?.returnPct ?? null
  const drawdownPct = summary?.maxDrawdownPct ?? null
  const tone = returnPct == null || returnPct === 0 ? '' : returnPct > 0 ? ' up' : ' down'
  return (
    <>
      <div className="metrics">
        <div className="metric">
          <p className="metric-label">Return</p>
          <p className={`metric-value${tone}`}>{returnPct == null ? '–' : signedPct(returnPct)}</p>
        </div>
        <div className="metric">
          <p className="metric-label">Max drawdown</p>
          <p className="metric-value">{drawdownPct == null ? '–' : pct(drawdownPct)}</p>
        </div>
      </div>
      <div className="backtest-row">
        <div>
          <p className="metric-label">Last backtest</p>
          <p className="backtest-when">{summary ? relativeTime(summary.createdAt) || 'Unknown' : 'Never run'}</p>
        </div>
        {summary ? (
          <button type="button" className="text-btn" onClick={() => onOpen(summary.id)}>
            View report
          </button>
        ) : null}
      </div>
    </>
  )
}

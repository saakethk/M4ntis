import { useEffect, useState } from 'react'
import { getBacktest, type BacktestReport } from '../api'

type Props = {
  id: number
  onOpenStrategy: (id: number) => void
}

export function BacktestPage({ id, onOpenStrategy }: Props) {
  const [report, setReport] = useState<BacktestReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let ignore = false
    setReport(null)
    setError(null)
    getBacktest(id)
      .then((next) => {
        if (!ignore) setReport(next)
      })
      .catch((caught: unknown) => {
        if (!ignore) setError(caught instanceof Error ? caught.message : 'Could not load this backtest.')
      })
    return () => {
      ignore = true
    }
  }, [id])

  return (
    <section className="backtest-page">
      <header className="backtest-page-head">
        <p className="plan-kicker">Backtest</p>
        <h1>{report ? report.strategyName : `Run ${id}`}</h1>
        <p className="plan-sub">
          {report
            ? `${formatWhen(report.createdAt)} · run ${report.id}${report.dummy ? ' · sample series' : ''}`
            : 'Loading this run…'}
        </p>
        {report ? (
          <button type="button" className="quiet" onClick={() => onOpenStrategy(report.strategyId)}>
            Back to strategy
          </button>
        ) : null}
      </header>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      {report ? <ReportBody report={report} /> : null}
    </section>
  )
}

// A strategy can order on every bar, so long runs list only the first orders.
const ORDER_ROWS = 200

function ReportBody({ report }: { report: BacktestReport }) {
  const metrics = report.metrics
  const buys = report.orders.filter((order) => order.side === 'buy').length
  const sells = report.orders.length - buys
  const shown = report.orders.slice(0, ORDER_ROWS)
  return (
    <div className="plan-grid">
      <article className="plan-card plan-teal">
        <h2>Overall performance</h2>
        <EquityChart points={report.balances.map((point) => point.equity)} />
        <dl className="plan-metrics">
          <Metric label="Ending equity" value={money(metrics.equity)} />
          <Metric label="Return" value={signedPct(metrics.returnPct)} tone={metrics.returnPct} />
          <Metric label="Gross P&L" value={signedMoney(metrics.grossPnl)} tone={metrics.grossPnl} />
          <Metric label="Max drawdown" value={pct(metrics.maxDrawdownPct)} />
          <Metric label="CAGR" value={metrics.cagrPct == null ? '–' : signedPct(metrics.cagrPct)} />
          <Metric label="Sharpe" value={metrics.sharpe == null ? '–' : metrics.sharpe.toFixed(2)} />
        </dl>
      </article>
      <article className="plan-card plan-navy">
        <h2>Trades</h2>
        <dl className="plan-metrics">
          <Metric label="Orders" value={count(report.orders.length)} />
          <Metric label="Buys / sells" value={`${count(buys)} / ${count(sells)}`} />
          <Metric label="Closed trades" value={count(metrics.numTrades)} />
          <Metric label="Won" value={String(metrics.numTradesWon)} />
          <Metric label="Lost" value={String(metrics.numTradesLost)} />
          <Metric label="Average win" value={metrics.avgWin == null ? '–' : money(metrics.avgWin)} />
          <Metric label="Average loss" value={metrics.avgLoss == null ? '–' : money(metrics.avgLoss)} />
          <Metric
            label="Expected P&L"
            value={metrics.expectedPnl == null ? '–' : signedMoney(metrics.expectedPnl)}
            tone={metrics.expectedPnl ?? 0}
          />
        </dl>
        {metrics.tradeReturns.length > 0 ? (
          <ul className="plan-rows">
            {metrics.tradeReturns.map((pnl, index) => (
              <li key={`${index}-${pnl}`}>
                <span className={pnl >= 0 ? 'up' : 'down'}>Trade {index + 1}</span>
                <span>{signedMoney(pnl)}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </article>
      <article className="plan-card plan-amber">
        <h2>Orders</h2>
        {report.orders.length === 0 ? <p className="plan-sub">The strategy never placed an order.</p> : null}
        {report.orders.length > shown.length ? (
          <p className="plan-sub">
            Showing the first {count(shown.length)} of {count(report.orders.length)} orders.
          </p>
        ) : null}
        <ul className="plan-rows">
          {shown.map((order, index) => (
            <li key={`${order.ts}-${order.side}-${index}`}>
              <span className={order.side === 'buy' ? 'up' : 'down'}>{order.side}</span>
              <span>
                {order.quantity} {order.symbol} at {money(order.price)}
              </span>
              <time dateTime={order.ts}>{formatWhen(order.ts)}</time>
            </li>
          ))}
        </ul>
      </article>
      <article className="plan-card plan-purple">
        <h2>Balance</h2>
        <ul className="plan-rows">
          {report.balances.map((point, index) => (
            <li key={`${point.ts}-${index}`}>
              <span>Equity {money(point.equity)}</span>
              <span>Cash {money(point.cash)}</span>
              <time dateTime={point.ts}>{formatWhen(point.ts)}</time>
            </li>
          ))}
        </ul>
      </article>
    </div>
  )
}

function Metric({ label, value, tone = 0 }: { label: string; value: string; tone?: number }) {
  const className = tone > 0 ? 'plan-value up' : tone < 0 ? 'plan-value down' : 'plan-value'
  return (
    <div>
      <dt>{label}</dt>
      <dd className={className}>{value}</dd>
    </div>
  )
}

function EquityChart({ points }: { points: number[] }) {
  if (points.length < 2) return null
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min || 1
  const width = 320
  const height = 88
  const line = points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * width
      const y = height - 8 - ((value - min) / span) * (height - 16)
      return `${x},${y}`
    })
    .join(' ')
  return (
    <svg className="equity-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Equity">
      <polyline points={line} />
    </svg>
  )
}

function count(value: number) {
  return value.toLocaleString('en-US')
}

function money(value: number) {
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function signedMoney(value: number) {
  const text = money(Math.abs(value))
  if (value > 0) return `+${text}`
  if (value < 0) return `-${text}`
  return text
}

function pct(value: number) {
  return `${value.toFixed(2)}%`
}

function signedPct(value: number) {
  const text = pct(Math.abs(value))
  if (value > 0) return `+${text}`
  if (value < 0) return `-${text}`
  return text
}

function formatWhen(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

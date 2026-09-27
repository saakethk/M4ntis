import { useEffect, useState } from 'react'
import { getBacktest, type BacktestReport } from '../../api/backtests.ts'
import { formatRangeSubtitle } from '../editor/backtestRange.ts'
import { dateTime, money, pct, signedMoney, signedPct } from '../../lib/format.ts'
import { BacktestAnalysis } from './BacktestAnalysis.tsx'

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
      .then((next) => !ignore && setReport(next))
      .catch((caught: unknown) => !ignore && setError(caught instanceof Error ? caught.message : 'Could not load this backtest.'))
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
            ? [
                formatRangeSubtitle(report.rangeStart, report.rangeEnd),
                `${dateTime(report.createdAt)} · run ${report.id}`,
              ]
                .filter(Boolean)
                .join(' · ')
            : error
              ? ''
              : 'Loading this run…'}
        </p>
        {report?.source === 'fpga' ? <p className="plan-sub">Ran on TradeCPU FPGA</p> : null}
        {report?.source === 'sample' ? (
          <p className="sample-banner">This run predates FPGA execution and used sample data, not your strategy on real prices.</p>
        ) : null}
        {report ? (
          <button type="button" className="quiet" onClick={() => onOpenStrategy(report.strategyId)}>
            ← Back to strategy
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

function ReportBody({ report }: { report: BacktestReport }) {
  const m = report.metrics
  const optional = (value: number | null, format: (v: number) => string) => (value == null ? '–' : format(value))
  return (
    <div className="plan-grid">
      <BacktestAnalysis backtestId={report.id} />
      <article className="plan-card plan-teal">
        <h2>Overall performance</h2>
        <EquityChart points={report.balances.map((point) => point.equity)} />
        <dl className="plan-metrics">
          <Metric label="Ending equity" value={money(m.equity)} />
          <Metric label="Return" value={signedPct(m.returnPct)} tone={m.returnPct} />
          <Metric label="Gross P&L" value={signedMoney(m.grossPnl)} tone={m.grossPnl} />
          <Metric label="Max drawdown" value={pct(m.maxDrawdownPct)} />
          <Metric label="CAGR" value={optional(m.cagrPct, signedPct)} />
          <Metric label="Sharpe" value={optional(m.sharpe, (v) => v.toFixed(2))} />
        </dl>
      </article>
      <article className="plan-card plan-navy">
        <h2>Trades</h2>
        <dl className="plan-metrics">
          <Metric label="Trades" value={String(m.numTrades)} />
          <Metric label="Won" value={String(m.numTradesWon)} />
          <Metric label="Lost" value={String(m.numTradesLost)} />
          <Metric label="Average win" value={optional(m.avgWin, money)} />
          <Metric label="Average loss" value={optional(m.avgLoss, money)} />
          <Metric label="Expected P&L" value={optional(m.expectedPnl, signedMoney)} tone={m.expectedPnl ?? 0} />
        </dl>
        {m.tradeReturns.length > 0 ? (
          <ul className="plan-rows">
            {m.tradeReturns.map((pnl, index) => (
              <li key={index}>
                <span className={pnl >= 0 ? 'up' : 'down'}>Trade {index + 1}</span>
                <span>{signedMoney(pnl)}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </article>
      <article className="plan-card plan-amber">
        <h2>Orders</h2>
        <ul className="plan-rows">
          {report.orders.map((order, index) => (
            <li key={index}>
              <span className={order.side === 'buy' ? 'up' : 'down'}>{order.side}</span>
              <span>
                {order.quantity} {order.symbol} at {money(order.price)}
              </span>
              <time dateTime={order.ts}>{dateTime(order.ts)}</time>
            </li>
          ))}
        </ul>
      </article>
      <article className="plan-card plan-purple">
        <h2>Balance</h2>
        <ul className="plan-rows">
          {report.balances.map((point, index) => (
            <li key={index}>
              <span>Equity {money(point.equity)}</span>
              <span>Cash {money(point.cash)}</span>
              <time dateTime={point.ts}>{dateTime(point.ts)}</time>
            </li>
          ))}
        </ul>
      </article>
    </div>
  )
}

function Metric({ label, value, tone = 0 }: { label: string; value: string; tone?: number }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className={tone > 0 ? 'plan-value up' : tone < 0 ? 'plan-value down' : 'plan-value'}>{value}</dd>
    </div>
  )
}

function EquityChart({ points }: { points: number[] }) {
  if (points.length < 2) return null
  const min = Math.min(...points)
  const span = Math.max(...points) - min || 1
  const width = 320
  const height = 88
  const line = points.map((value, i) => `${(i / (points.length - 1)) * width},${height - 8 - ((value - min) / span) * (height - 16)}`).join(' ')
  return (
    <svg className="equity-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Equity over the run">
      <polyline points={line} />
    </svg>
  )
}

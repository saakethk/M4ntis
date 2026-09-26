import { STRATEGIES, formatPct, totalReturn } from '../strategies'

export function Portfolio() {
  const total = totalReturn(STRATEGIES)

  return (
    <section className="portfolio">
      <header className="page-head">
        <h1>Strategy Portfolio</h1>
        <p className="subtitle">
          {STRATEGIES.length} strategies · {formatPct(total)} total backtested return
        </p>
      </header>
      <div className="cards">
        {STRATEGIES.map((strategy) => (
          <article key={strategy.id} className="card">
            <div className="card-top">
              <div>
                <h2>{strategy.name}</h2>
                <p className="meta">
                  {strategy.symbol} · {strategy.timeframe}
                </p>
              </div>
              <p className={strategy.returnPct < 0 ? 'pct down' : 'pct up'}>
                {formatPct(strategy.returnPct)}
              </p>
            </div>
            <div
              className={strategy.returnPct < 0 ? 'chart down' : 'chart'}
              aria-hidden="true"
            >
              {strategy.bars.map((height, index) => (
                <span key={`${strategy.id}-${index}`} style={{ height: `${height}%` }} />
              ))}
            </div>
            <div className="card-actions">
              <button type="button" className="secondary">
                Backtest
              </button>
              <button type="button" className="ghost">
                Edit
              </button>
            </div>
          </article>
        ))}
        <button type="button" className="card new-card">
          <span className="plus" aria-hidden="true">
            +
          </span>
          New Strategy
        </button>
      </div>
    </section>
  )
}

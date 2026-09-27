import { RESOLUTIONS } from '../../blocks/hardware.ts'
import type { BlockNode } from '../../blocks/types.ts'
import { START_NODE_ID } from '../../flow/graph.ts'
import { tickerSymbols } from '../../flow/tickers.ts'
import { money } from '../../lib/format.ts'

type Props = {
  nodes: BlockNode[]
  running: boolean
  disabled: boolean
  canRun: boolean
  onRun: () => void
}

/** What a run will use (read from the Start and Get ticker blocks) and the button to start it. */
export function BacktestPanel({ nodes, running, disabled, canRun, onRun }: Props) {
  const start = nodes.find((node) => node.id === START_NODE_ID)?.data.params ?? {}
  const resolution = RESOLUTIONS.find((r) => r.value === start.resolution)?.label ?? String(start.resolution ?? '')
  const tickers = tickerSymbols(nodes).filter(Boolean)

  return (
    <section className="rail-panel" aria-label="Backtest">
      <header className="rail-head">
        <h2>Backtest</h2>
        <p>Settings come from the Start block and your Get ticker blocks.</p>
      </header>
      <dl className="rail-facts">
        <div>
          <dt>Starting balance</dt>
          <dd>{money(Number(start.startingBalance ?? 0))}</dd>
        </div>
        <div>
          <dt>Tick every</dt>
          <dd>{resolution}</dd>
        </div>
        <div>
          <dt>Stocks</dt>
          <dd>{tickers.length > 0 ? tickers.join(', ') : 'None yet'}</dd>
        </div>
      </dl>
      <p className="rail-note">Runs currently replay a fixed sample series while the market-data simulator is built. Saving happens first.</p>
      <button type="button" className="rail-action" onClick={onRun} disabled={disabled || running || !canRun}>
        {running ? 'Running…' : 'Run backtest'}
      </button>
      {!canRun ? <p className="rail-note">Save your own copy to run backtests.</p> : null}
    </section>
  )
}

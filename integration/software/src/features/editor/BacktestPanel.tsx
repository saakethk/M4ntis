import { useCallback, useEffect, useState } from 'react'
import { getFpgaStatus, type FpgaStatus } from '../../api/backtests.ts'
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

/** What a run will use (read from the Start and Get ticker blocks), whether the FPGA is attached, and the button to start it. */
export function BacktestPanel({ nodes, running, disabled, canRun, onRun }: Props) {
  const start = nodes.find((node) => node.id === START_NODE_ID)?.data.params ?? {}
  const resolution = RESOLUTIONS.find((r) => r.value === start.resolution)?.label ?? String(start.resolution ?? '')
  const tickers = tickerSymbols(nodes).filter(Boolean)
  const [board, setBoard] = useState<FpgaStatus | null>(null)
  const [checking, setChecking] = useState(true)
  const [boardError, setBoardError] = useState<string | null>(null)

  const refresh = useCallback(() => {
    setChecking(true)
    getFpgaStatus()
      .then((next) => {
        setBoard(next)
        setBoardError(null)
      })
      .catch((caught: unknown) => setBoardError(caught instanceof Error ? caught.message : 'Could not check the FPGA.'))
      .finally(() => setChecking(false))
  }, [])

  useEffect(() => {
    if (!running) refresh()
  }, [running, refresh])

  const connected = board?.connected === true && boardError == null

  return (
    <section className="rail-panel" aria-label="Backtest">
      <header className="rail-head">
        <h2>Backtest</h2>
        <p>Settings come from the Start block and your Get ticker blocks.</p>
      </header>
      <div className={`fpga-status ${connected ? 'on' : 'off'}`} role="status">
        <span>
          {checking && board == null
            ? 'Checking for the TradeCPU FPGA…'
            : boardError
              ? boardError
              : connected
                ? `TradeCPU FPGA: ${board?.busy ? 'busy' : 'connected'} at ${board?.port}`
                : `TradeCPU FPGA not connected. ${board?.detail ?? ''}`}
        </span>
        <button type="button" className="quiet" onClick={refresh} disabled={checking || running}>
          Refresh
        </button>
      </div>
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
      <p className="rail-note">Runs feed the latest ~500 ticks of real price history to the board. Saving happens first.</p>
      <button type="button" className="rail-action" onClick={onRun} disabled={disabled || running || !canRun || !connected}>
        {running ? 'Running on FPGA…' : 'Run on FPGA'}
      </button>
      {!connected && !checking ? (
        <p className="rail-note">Backtests only run on the TradeCPU FPGA. Running one is not possible until the board is connected.</p>
      ) : null}
      {!canRun ? <p className="rail-note">Save your own copy to run backtests.</p> : null}
    </section>
  )
}

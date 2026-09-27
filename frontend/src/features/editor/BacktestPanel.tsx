import { useCallback, useEffect, useMemo, useState } from 'react'
import { getBacktestRange, getFpgaStatus, type BacktestRange, type FpgaStatus } from '../../api/backtests.ts'
import { RESOLUTIONS } from '../../blocks/hardware.ts'
import type { BlockNode } from '../../blocks/types.ts'
import { START_NODE_ID } from '../../flow/graph.ts'
import { tickerSymbols } from '../../flow/tickers.ts'
import { money } from '../../lib/format.ts'
import {
  formatShortDate,
  isRangeValid,
  snapToAvailableDay,
  type BacktestRangeChoice,
} from './backtestRange.ts'

type Props = {
  nodes: BlockNode[]
  strategyId: number | null
  saveCount: number
  running: boolean
  disabled: boolean
  canRun: boolean
  onRun: (range: BacktestRangeChoice) => void
}

/** What a run will use (read from the Start and Get ticker blocks), whether the FPGA is attached, and the button to start it. */
export function BacktestPanel({ nodes, strategyId, saveCount, running, disabled, canRun, onRun }: Props) {
  const start = nodes.find((node) => node.id === START_NODE_ID)?.data.params ?? {}
  const resolution = RESOLUTIONS.find((r) => r.value === start.resolution)?.label ?? String(start.resolution ?? '')
  const tickers = tickerSymbols(nodes).filter(Boolean)
  const marketKey = `${tickers.join(',')}|${String(start.resolution ?? '')}`
  const [board, setBoard] = useState<FpgaStatus | null>(null)
  const [checking, setChecking] = useState(true)
  const [boardError, setBoardError] = useState<string | null>(null)
  const [available, setAvailable] = useState<BacktestRange | null>(null)
  const [rangeError, setRangeError] = useState<string | null>(null)
  const [loadingRange, setLoadingRange] = useState(false)
  const [useLatest, setUseLatest] = useState(true)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [rangeHint, setRangeHint] = useState<string | null>(null)

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

  useEffect(() => {
    if (strategyId == null) {
      setAvailable(null)
      setRangeError(null)
      return
    }
    let ignore = false
    setLoadingRange(true)
    getBacktestRange(strategyId)
      .then((next) => {
        if (ignore) return
        setAvailable(next)
        setRangeError(null)
      })
      .catch((caught: unknown) => {
        if (ignore) return
        setAvailable(null)
        setRangeError(caught instanceof Error ? caught.message : 'Could not load available dates.')
      })
      .finally(() => {
        if (!ignore) setLoadingRange(false)
      })
    return () => {
      ignore = true
    }
  }, [strategyId, saveCount, marketKey])

  const days = available?.days ?? []
  const minDay = available?.start ?? ''
  const maxDay = available?.end ?? ''

  const rangeChoice = useMemo((): BacktestRangeChoice => {
    if (useLatest) return null
    if (!startDate || !endDate) return null
    return { start: startDate, end: endDate }
  }, [useLatest, startDate, endDate])

  const rangeOk = isRangeValid(startDate || null, endDate || null, days, useLatest)

  function pickStart(next: string) {
    setRangeHint(null)
    if (!next) {
      setStartDate('')
      return
    }
    const snapped = snapToAvailableDay(next, days)
    setStartDate(snapped.date)
    if (snapped.hint) setRangeHint(snapped.hint)
    if (endDate && snapped.date > endDate) setEndDate(snapped.date)
  }

  function pickEnd(next: string) {
    setRangeHint(null)
    if (!next) {
      setEndDate('')
      return
    }
    const snapped = snapToAvailableDay(next, days)
    setEndDate(snapped.date)
    if (snapped.hint) setRangeHint(snapped.hint)
    if (startDate && snapped.date < startDate) setStartDate(snapped.date)
  }

  function useLatestMode() {
    setUseLatest(true)
    setRangeHint(null)
  }

  function useCustomMode() {
    setUseLatest(false)
    if (!startDate && minDay) setStartDate(minDay)
    if (!endDate && maxDay) setEndDate(maxDay)
  }

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
      <div className="backtest-range">
        <div className="backtest-range-head">
          <h3>Date range</h3>
          <div className="backtest-range-presets">
            <button type="button" className={`quiet compact${useLatest ? ' active' : ''}`} onClick={useLatestMode} disabled={running}>
              Latest
            </button>
            <button
              type="button"
              className={`quiet compact${!useLatest ? ' active' : ''}`}
              onClick={useCustomMode}
              disabled={running || strategyId == null}
            >
              Custom
            </button>
          </div>
        </div>
        {strategyId == null ? (
          <p className="rail-note">Save to pick a date range.</p>
        ) : loadingRange ? (
          <p className="rail-note">Loading available dates…</p>
        ) : rangeError ? (
          <p className="rail-note">{rangeError}</p>
        ) : days.length === 0 ? (
          <p className="rail-note">No price data for these stocks yet.</p>
        ) : (
          <>
            <p className="rail-note">
              Data available: {formatShortDate(minDay)} – {formatShortDate(maxDay)} · {days.length} trading days
            </p>
            {!useLatest ? (
              <div className="backtest-range-fields">
                <label>
                  Start
                  <input
                    type="date"
                    value={startDate}
                    min={minDay}
                    max={maxDay}
                    disabled={running}
                    onChange={(event) => pickStart(event.target.value)}
                  />
                </label>
                <label>
                  End
                  <input
                    type="date"
                    value={endDate}
                    min={minDay}
                    max={maxDay}
                    disabled={running}
                    onChange={(event) => pickEnd(event.target.value)}
                  />
                </label>
              </div>
            ) : (
              <p className="rail-note">Uses the latest ~500 ticks after warm-up.</p>
            )}
            {rangeHint ? <p className="rail-note">{rangeHint}</p> : null}
          </>
        )}
      </div>
      <button
        type="button"
        className="rail-action"
        onClick={() => onRun(rangeChoice)}
        disabled={disabled || running || !canRun || !connected || (!useLatest && !rangeOk)}
      >
        {running ? 'Running on FPGA…' : 'Run on FPGA'}
      </button>
      {!connected && !checking ? (
        <p className="rail-note">Backtests only run on the TradeCPU FPGA. Running one is not possible until the board is connected.</p>
      ) : null}
      {!canRun ? <p className="rail-note">Save your own copy to run backtests.</p> : null}
    </section>
  )
}

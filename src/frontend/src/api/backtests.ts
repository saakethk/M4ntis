import { id, list, num, optionalNum, optionalStr, postJson, record, requestJson, str } from './http.ts'

export type BacktestOrder = {
  ts: string
  symbol: string
  side: string
  quantity: number
  price: number
}

export type BacktestBalance = {
  ts: string
  cash: number
  equity: number
}

export type BacktestMetrics = {
  equity: number
  returnPct: number
  maxDrawdownPct: number
  grossPnl: number
  cagrPct: number | null
  sharpe: number | null
  numTrades: number
  numTradesWon: number
  numTradesLost: number
  avgWin: number | null
  avgLoss: number | null
  expectedPnl: number | null
  tradeReturns: number[]
}

export type FpgaStatus = {
  connected: boolean
  port: string | null
  busy: boolean
  detail: string
}

export type BacktestRange = {
  symbols: string[]
  resolution: string
  start: string | null
  end: string | null
  days: string[]
}

export type BacktestReport = {
  id: number
  strategyId: number
  strategyName: string
  createdAt: string
  /** `fpga` for runs on the TradeCPU board; `sample` for runs from before FPGA execution. */
  source: string
  rangeStart: string | null
  rangeEnd: string | null
  orders: BacktestOrder[]
  balances: BacktestBalance[]
  metrics: BacktestMetrics
}

const WHAT = 'Backtest'

/** Start a run and return its id. Omit ``range`` to use the latest bars. */
export async function runBacktest(
  userId: number,
  strategyId: number,
  range?: { start: string; end: string } | null,
): Promise<number> {
  const body: Record<string, unknown> = { user_id: userId, strategy_id: strategyId }
  if (range) {
    body.start = range.start
    body.end = range.end
  }
  return id(record(await postJson('/backtests', body), WHAT).id, WHAT)
}

/** Calendar days with minute bars for every stock the strategy reads. */
export async function getBacktestRange(strategyId: number): Promise<BacktestRange> {
  const row = record(await requestJson(`/backtests/range?strategy_id=${strategyId}`), 'Backtest range')
  const days = list(row.days, 'Backtest range')
  if (days.some((item) => typeof item !== 'string')) throw new Error('Backtest range response was not valid.')
  return {
    symbols: list(row.symbols, 'Backtest range').map((item) => String(item)),
    resolution: str(row, 'resolution', 'Backtest range'),
    start: optionalStr(row, 'start'),
    end: optionalStr(row, 'end'),
    days: days as string[],
  }
}

/** Whether the TradeCPU board is attached. Backtests are refused without it. */
export async function getFpgaStatus(): Promise<FpgaStatus> {
  const row = record(await requestJson('/backtests/fpga'), 'FPGA status')
  return {
    connected: row.connected === true,
    port: typeof row.port === 'string' ? row.port : null,
    busy: row.busy === true,
    detail: str(row, 'detail', 'FPGA status'),
  }
}

export async function getBacktest(backtestId: number): Promise<BacktestReport> {
  const row = record(await requestJson(`/backtests/${backtestId}`), WHAT)
  return {
    id: id(row.id, WHAT),
    strategyId: id(row.strategy_id, WHAT),
    strategyName: str(row, 'strategy_name', WHAT),
    createdAt: optionalStr(row, 'created_at'),
    source: str(row, 'source', WHAT),
    rangeStart: optionalStr(row, 'range_start'),
    rangeEnd: optionalStr(row, 'range_end'),
    orders: list(row.orders, WHAT).map(readOrder),
    balances: list(row.balances, WHAT).map(readBalance),
    metrics: readMetrics(row.metrics),
  }
}

function readOrder(body: unknown): BacktestOrder {
  const row = record(body, WHAT)
  return {
    ts: optionalStr(row, 'ts'),
    symbol: str(row, 'symbol', WHAT),
    side: str(row, 'side', WHAT),
    quantity: num(row, 'quantity', WHAT),
    price: num(row, 'price', WHAT),
  }
}

function readBalance(body: unknown): BacktestBalance {
  const row = record(body, WHAT)
  return { ts: optionalStr(row, 'ts'), cash: num(row, 'cash', WHAT), equity: num(row, 'equity', WHAT) }
}

function readMetrics(body: unknown): BacktestMetrics {
  const row = record(body, WHAT)
  const returns = list(row.trade_returns, WHAT)
  if (returns.some((item) => typeof item !== 'number')) throw new Error(`${WHAT} response was not valid.`)
  return {
    equity: num(row, 'equity', WHAT),
    returnPct: num(row, 'return_pct', WHAT),
    maxDrawdownPct: num(row, 'max_drawdown_pct', WHAT),
    grossPnl: num(row, 'gross_pnl', WHAT),
    cagrPct: optionalNum(row, 'cagr_pct', WHAT),
    sharpe: optionalNum(row, 'sharpe', WHAT),
    numTrades: num(row, 'num_trades', WHAT),
    numTradesWon: num(row, 'num_trades_won', WHAT),
    numTradesLost: num(row, 'num_trades_lost', WHAT),
    avgWin: optionalNum(row, 'avg_win_amount', WHAT),
    avgLoss: optionalNum(row, 'avg_loss_amount', WHAT),
    expectedPnl: optionalNum(row, 'expected_pnl_per_trade', WHAT),
    tradeReturns: returns as number[],
  }
}

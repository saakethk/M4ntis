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

export type BacktestReport = {
  id: number
  strategyId: number
  strategyName: string
  createdAt: string
  /** `fpga` for runs on the TradeCPU board; `sample` for runs from before FPGA execution. */
  source: string
  orders: BacktestOrder[]
  balances: BacktestBalance[]
  metrics: BacktestMetrics
}

const WHAT = 'Backtest'

/** Start a run and return its id. */
export async function runBacktest(userId: number, strategyId: number): Promise<number> {
  return id(record(await postJson('/backtests', { user_id: userId, strategy_id: strategyId }), WHAT).id, WHAT)
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

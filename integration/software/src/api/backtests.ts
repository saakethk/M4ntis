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

export type BacktestReport = {
  id: number
  strategyId: number
  strategyName: string
  createdAt: string
  /** True while runs use the sample series instead of simulated market data. */
  sample: boolean
  orders: BacktestOrder[]
  balances: BacktestBalance[]
  metrics: BacktestMetrics
}

const WHAT = 'Backtest'

/** Start a run and return its id. */
export async function runBacktest(userId: number, strategyId: number): Promise<number> {
  return id(record(await postJson('/backtests', { user_id: userId, strategy_id: strategyId }), WHAT).id, WHAT)
}

export async function getBacktest(backtestId: number): Promise<BacktestReport> {
  const row = record(await requestJson(`/backtests/${backtestId}`), WHAT)
  return {
    id: id(row.id, WHAT),
    strategyId: id(row.strategy_id, WHAT),
    strategyName: str(row, 'strategy_name', WHAT),
    createdAt: optionalStr(row, 'created_at'),
    sample: row.dummy === true,
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

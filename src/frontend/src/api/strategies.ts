import { id, isRecord, list, optionalNum, optionalStr, postJson, putJson, record, requestJson, str } from './http.ts'

export type Visibility = 'private' | 'public'

export type StrategySummary = {
  id: number
  name: string
  visibility: Visibility
  updatedAt: string
  lastBacktest: BacktestSummary | null
}

/** Headline figures of a strategy's most recent backtest. Metrics are null when they could not be computed. */
export type BacktestSummary = {
  id: number
  createdAt: string
  source: string
  returnPct: number | null
  maxDrawdownPct: number | null
  numTrades: number | null
}

export type StrategyRecord = {
  id: number
  name: string
  document: unknown
  owned: boolean
}

export type StrategyVersion = {
  id: number
  name: string
  createdAt: string
}

export type StrategyWrite = {
  name: string
  document: unknown
  ir: unknown
}

export async function listStrategies(): Promise<StrategySummary[]> {
  return list(await requestJson('/strategies'), 'Strategy').map(readSummary)
}

export async function getStrategy(strategyId: number): Promise<StrategyRecord> {
  return readRecord(await requestJson(`/strategies/${strategyId}`))
}

export async function createStrategy(body: StrategyWrite): Promise<StrategySummary> {
  return readSummary(await postJson('/strategies', { ...body, visibility: 'private' }))
}

export async function updateStrategy(strategyId: number, body: StrategyWrite): Promise<StrategySummary> {
  return readSummary(await putJson(`/strategies/${strategyId}`, body))
}

export async function listStrategyVersions(strategyId: number): Promise<StrategyVersion[]> {
  return list(await requestJson(`/strategies/${strategyId}/versions`), 'Version').map((body) => {
    const row = record(body, 'Version')
    return { id: id(row.id, 'Version'), name: str(row, 'name', 'Version'), createdAt: optionalStr(row, 'created_at') }
  })
}

export async function revertStrategyVersion(strategyId: number, versionId: number): Promise<StrategyRecord> {
  return readRecord(await postJson(`/strategies/${strategyId}/versions/${versionId}/revert`))
}

function readSummary(body: unknown): StrategySummary {
  const row = record(body, 'Strategy')
  return {
    id: id(row.id, 'Strategy'),
    name: str(row, 'name', 'Strategy'),
    visibility: row.visibility === 'public' ? 'public' : 'private',
    updatedAt: optionalStr(row, 'updated_at'),
    lastBacktest: isRecord(row.last_backtest) ? readBacktestSummary(row.last_backtest) : null,
  }
}

function readBacktestSummary(row: Record<string, unknown>): BacktestSummary {
  return {
    id: id(row.id, 'Backtest'),
    createdAt: optionalStr(row, 'created_at'),
    source: optionalStr(row, 'source'),
    returnPct: optionalNum(row, 'return_pct', 'Backtest'),
    maxDrawdownPct: optionalNum(row, 'max_drawdown_pct', 'Backtest'),
    numTrades: optionalNum(row, 'num_trades', 'Backtest'),
  }
}

function readRecord(body: unknown): StrategyRecord {
  const row = record(body, 'Strategy')
  return {
    id: id(row.id, 'Strategy'),
    name: str(row, 'name', 'Strategy'),
    // Older rows stored the document as a JSON string.
    document: typeof row.document === 'string' ? JSON.parse(row.document) : row.document,
    owned: row.owned !== false,
  }
}

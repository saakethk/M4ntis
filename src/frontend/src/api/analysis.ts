import { postJson, record, str } from './http.ts'

export type BacktestAnalysis = {
  analysis: string
  model: string
}

/** Ask the chosen model to explain a finished backtest, optionally answering a question about it. */
export async function analyzeBacktest(
  backtestId: number,
  request: { choice: { provider: string; model: string } | null; question: string },
): Promise<BacktestAnalysis> {
  const row = record(
    await postJson(`/backtests/${backtestId}/analysis`, {
      question: request.question,
      ...(request.choice ? { provider: request.choice.provider, model: request.choice.model } : {}),
    }),
    'Analysis',
  )
  return { analysis: str(row, 'analysis', 'Analysis'), model: typeof row.model === 'string' ? row.model : '' }
}

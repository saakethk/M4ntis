// Pure helpers for the portfolio page, kept separate so they can be unit tested.

import type { StrategySummary, Visibility } from '../../api/strategies.ts'

export type VisibilityFilter = 'all' | Visibility

export type PortfolioView = 'loading' | 'error' | 'get-started' | 'list'

/** Get Started is shown only for a successful, empty load; a failed load stays an error. */
export function portfolioView(input: { loading: boolean; failed: boolean; count: number }): PortfolioView {
  if (input.loading) return 'loading'
  if (input.failed) return 'error'
  return input.count === 0 ? 'get-started' : 'list'
}

export function filterStrategies(rows: readonly StrategySummary[], query: string, visibility: VisibilityFilter): StrategySummary[] {
  const needle = query.trim().toLowerCase()
  return rows.filter(
    (row) => (needle === '' || row.name.toLowerCase().includes(needle)) && (visibility === 'all' || row.visibility === visibility),
  )
}

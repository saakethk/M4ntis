export type StrategyStatus = 'active' | 'ready' | 'backtesting' | 'draft'

export type Strategy = {
  id: string
  name: string
  status: StrategyStatus
  createdLabel: string
  returnPct: number | null
  maxDrawdownPct: number | null
  lastBacktest: string
}

export type SavedStrategy = {
  id: number
  name: string
}

export type PortfolioChoice = 'loading' | 'error' | 'get-started' | 'list'

// Rows saved for this account. An empty list and a failed request both yield
// no cards, so the built-in sample strategies are never shown in their place.
export function portfolioStrategies(rows: readonly SavedStrategy[] | null): Strategy[] {
  if (rows == null || rows.length === 0) return []
  return rows.map((row) => ({
    id: String(row.id),
    name: row.name,
    status: 'draft',
    createdLabel: 'Saved strategy',
    returnPct: null,
    maxDrawdownPct: null,
    lastBacktest: 'Never run',
  }))
}

// Get Started is only the successful empty portfolio. A failed load stays an
// error, and any saved row keeps the strategy list.
export function portfolioChoice(input: { loading: boolean; failed: boolean; count: number }): PortfolioChoice {
  if (input.loading) return 'loading'
  if (input.failed) return 'error'
  if (input.count === 0) return 'get-started'
  return 'list'
}

export function formatPct(value: number): string {
  const text = value.toFixed(1)
  return value > 0 ? `+${text}%` : `${text}%`
}

export function formatDrawdown(value: number): string {
  return `${value.toFixed(1)}%`
}

export function displayName(email: string): string {
  const local = email.split('@')[0]?.trim() ?? ''
  const words = local.split(/[._+-]+/).filter(Boolean)
  if (words.length === 0) return email
  return words.map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')
}

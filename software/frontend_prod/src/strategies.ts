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

export const DUMMY_BALANCE = '$10,000'

export const STRATEGIES: Strategy[] = [
  {
    id: 'mean-reversion',
    name: 'Mean Reversion / SPY',
    status: 'active',
    createdLabel: 'Created 2 weeks ago',
    returnPct: 24.8,
    maxDrawdownPct: 6.4,
    lastBacktest: '2 hours ago',
  },
  {
    id: 'trend-following',
    name: 'Trend Following Tech',
    status: 'ready',
    createdLabel: 'Created 2 weeks ago',
    returnPct: 18.2,
    maxDrawdownPct: 8.5,
    lastBacktest: '3 days ago',
  },
  {
    id: 'volatility-breakout',
    name: 'Volatility Breakout',
    status: 'backtesting',
    createdLabel: 'Created 2 weeks ago',
    returnPct: null,
    maxDrawdownPct: null,
    lastBacktest: 'Running now',
  },
  {
    id: 'arbitrage-experiment',
    name: 'Arbitrage Experiment',
    status: 'draft',
    createdLabel: 'Created 2 weeks ago',
    returnPct: null,
    maxDrawdownPct: null,
    lastBacktest: 'Never run',
  },
]

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

export type Strategy = {
  id: string
  name: string
  symbol: string
  timeframe: string
  returnPct: number
  bars: number[]
}

export const DUMMY_BALANCE = '$10,000'

export const STRATEGIES: Strategy[] = [
  {
    id: 'mean-reversion',
    name: 'Mean Reversion',
    symbol: 'SPY',
    timeframe: '1 hour',
    returnPct: 24.8,
    bars: [32, 40, 36, 48, 44, 58, 52, 66, 61, 74, 70, 82],
  },
  {
    id: 'trend-following',
    name: 'Trend Following',
    symbol: 'QQQ',
    timeframe: '1 hour',
    returnPct: 18.2,
    bars: [28, 34, 46, 42, 55, 50, 63, 58, 70, 66, 72, 78],
  },
  {
    id: 'volatility-breakout',
    name: 'Volatility Breakout',
    symbol: 'IWM',
    timeframe: '1 hour',
    returnPct: -4.1,
    bars: [70, 64, 72, 58, 60, 48, 52, 40, 44, 36, 38, 30],
  },
  {
    id: 'opening-range',
    name: 'Opening Range',
    symbol: 'AAPL',
    timeframe: '1 hour',
    returnPct: 9.6,
    bars: [22, 30, 28, 36, 44, 40, 48, 55, 50, 58, 62, 68],
  },
]

export function totalReturn(strategies: Strategy[]): number {
  return strategies.reduce((sum, strategy) => sum + strategy.returnPct, 0)
}

export function formatPct(value: number): string {
  const text = value.toFixed(1)
  return value > 0 ? `+${text}%` : `${text}%`
}

export function displayName(email: string): string {
  const local = email.split('@')[0]?.trim() ?? ''
  const words = local.split(/[._+-]+/).filter(Boolean)
  if (words.length === 0) return email
  return words.map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')
}

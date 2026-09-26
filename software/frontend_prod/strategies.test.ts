import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { STRATEGIES, portfolioStrategies } from './src/strategies.ts'

const DEFAULT_NAMES = [
  'Mean Reversion / SPY',
  'Trend Following Tech',
  'Volatility Breakout',
  'Arbitrage Experiment',
]

describe('portfolioStrategies', () => {
  it('shows the built-in sample cards when the list request fails', () => {
    const shown = portfolioStrategies(null)
    assert.deepEqual(
      shown.map((strategy) => strategy.name),
      DEFAULT_NAMES,
    )
    assert.equal(shown, STRATEGIES)
    assert.equal(shown[0].returnPct, 24.8)
  })

  it('shows the built-in sample cards when the signed-in user has no saved strategies', () => {
    const shown = portfolioStrategies([])
    assert.deepEqual(
      shown.map((strategy) => strategy.id),
      ['mean-reversion', 'trend-following', 'volatility-breakout', 'arbitrage-experiment'],
    )
    assert.equal(shown, STRATEGIES)
  })

  it('keeps saved strategies and does not append the samples', () => {
    const shown = portfolioStrategies([
      { id: 7, name: 'Opening Drive' },
      { id: 8, name: 'Close Auction' },
    ])
    assert.deepEqual(
      shown.map((strategy) => strategy.name),
      ['Opening Drive', 'Close Auction'],
    )
    assert.deepEqual(
      shown.map((strategy) => strategy.id),
      ['7', '8'],
    )
    assert.equal(shown[0].returnPct, STRATEGIES[0].returnPct)
    assert.equal(shown[1].status, STRATEGIES[1].status)
    assert.equal(
      shown.some((strategy) => DEFAULT_NAMES.includes(strategy.name)),
      false,
    )
  })
})

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { portfolioChoice, portfolioStrategies } from './src/strategies.ts'

const SAMPLE_NAMES = [
  'Mean Reversion / SPY',
  'Trend Following Tech',
  'Volatility Breakout',
  'Arbitrage Experiment',
]

describe('portfolioStrategies', () => {
  it('returns no cards when the list request fails', () => {
    assert.deepEqual(portfolioStrategies(null), [])
  })

  it('returns no cards when the signed-in user has no saved strategies', () => {
    assert.deepEqual(portfolioStrategies([]), [])
  })

  it('keeps saved strategies and does not append sample cards or sample stats', () => {
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
    assert.equal(shown[0].returnPct, null)
    assert.equal(shown[0].maxDrawdownPct, null)
    assert.equal(shown[0].status, 'draft')
    assert.equal(
      shown.some((strategy) => SAMPLE_NAMES.includes(strategy.name)),
      false,
    )
  })
})

describe('portfolioChoice', () => {
  it('shows Get Started only for a successful empty portfolio', () => {
    assert.equal(portfolioChoice({ loading: false, failed: false, count: 0 }), 'get-started')
  })

  it('keeps a failed load as an error instead of Get Started', () => {
    assert.equal(portfolioChoice({ loading: false, failed: true, count: 0 }), 'error')
  })

  it('lists saved strategies when the request returns rows', () => {
    assert.equal(portfolioChoice({ loading: false, failed: false, count: 2 }), 'list')
  })

  it('stays on loading until the request settles', () => {
    assert.equal(portfolioChoice({ loading: true, failed: false, count: 0 }), 'loading')
  })
})

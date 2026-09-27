import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { parseRoute, routePath } from './src/routes.ts'

describe('parseRoute', () => {
  it('reads the portfolio home', () => {
    assert.deepEqual(parseRoute('/'), { kind: 'home' })
    assert.deepEqual(parseRoute(''), { kind: 'home' })
  })

  it('reads the discussions page', () => {
    assert.deepEqual(parseRoute('/discussions'), { kind: 'discussions' })
    assert.deepEqual(parseRoute('/discussions/'), { kind: 'discussions' })
  })

  it('reads a new unsaved strategy', () => {
    assert.deepEqual(parseRoute('/strategy/new'), { kind: 'new' })
    assert.deepEqual(parseRoute('/strategy/new/'), { kind: 'new' })
  })

  it('reads an existing strategy id', () => {
    assert.deepEqual(parseRoute('/strategy/12'), { kind: 'edit', id: 12 })
    assert.deepEqual(parseRoute('/strategy/12/'), { kind: 'edit', id: 12 })
  })

  it('reads a saved backtest', () => {
    assert.deepEqual(parseRoute('/backtest/3'), { kind: 'backtest', id: 3 })
    assert.deepEqual(parseRoute('/backtest/3/'), { kind: 'backtest', id: 3 })
  })

  it('does not treat a non-id backtest path as a report', () => {
    assert.deepEqual(parseRoute('/backtest/new'), { kind: 'unavailable' })
    assert.deepEqual(parseRoute('/backtest/0'), { kind: 'unavailable' })
  })

  it('does not treat a non-id strategy path as an opened project', () => {
    assert.deepEqual(parseRoute('/strategy/mean-reversion'), { kind: 'unavailable' })
    assert.deepEqual(parseRoute('/strategy/0'), { kind: 'unavailable' })
    assert.deepEqual(parseRoute('/strategy/new/1'), { kind: 'unavailable' })
  })
})

describe('routePath', () => {
  it('builds the portfolio and strategy urls', () => {
    assert.equal(routePath({ kind: 'home' }), '/')
    assert.equal(routePath({ kind: 'discussions' }), '/discussions')
    assert.equal(routePath({ kind: 'new' }), '/strategy/new')
    assert.equal(routePath({ kind: 'edit', id: 4 }), '/strategy/4')
    assert.equal(routePath({ kind: 'backtest', id: 3 }), '/backtest/3')
    assert.equal(routePath({ kind: 'unavailable' }), null)
  })

  it('round-trips paths that open a screen', () => {
    for (const path of ['/', '/strategy/new', '/strategy/9', '/backtest/3']) {
      const screen = parseRoute(path)
      assert.equal(routePath(screen), path)
    }
  })
})

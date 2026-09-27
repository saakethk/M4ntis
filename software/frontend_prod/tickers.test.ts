import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { makeNode, START_NODE_ID, assignPriceTicker, tickerSymbols } from './src/flow/graph.ts'
import { toDocument } from './src/flow/serialize.ts'

function priceGraph() {
  return [
    makeNode('start', { x: 0, y: 0 }, { startingBalance: 100000, resolution: '5m' }, START_NODE_ID),
    makeNode('price_n_ticks_ago', { x: 200, y: 80 }, { buffer: 0, n: 10 }, 'price'),
  ]
}

describe('assignPriceTicker', () => {
  it('stores the symbol on Start when the graph has no Get ticker block', () => {
    const nodes = assignPriceTicker(priceGraph(), 'price', 'msft')
    const start = nodes.find((n) => n.id === START_NODE_ID)
    const price = nodes.find((n) => n.id === 'price')
    assert.equal(start?.data.params.symbol0, 'MSFT')
    assert.equal(price?.data.params.symbol, 'MSFT')
    assert.equal(price?.data.params.buffer, 0)
    assert.equal(nodes.some((n) => n.type === 'get_ticker'), false)
    assert.equal(tickerSymbols(nodes)[0], 'MSFT')
  })

  it('reuses a Start slot that already has that symbol', () => {
    const nodes = assignPriceTicker(
      [
        makeNode(
          'start',
          { x: 0, y: 0 },
          { symbol0: 'AAPL', symbol1: 'MSFT' },
          START_NODE_ID,
        ),
        makeNode('price_n_ticks_ago', { x: 0, y: 0 }, { buffer: 0, n: 4 }, 'price'),
      ],
      'price',
      'msft',
    )
    assert.equal(nodes.find((n) => n.id === 'price')?.data.params.buffer, 1)
    assert.equal(nodes.filter((n) => n.id === START_NODE_ID)[0].data.params.symbol0, 'AAPL')
  })

  it('reuses a Get ticker block and does not add another', () => {
    const nodes = assignPriceTicker(
      [
        ...priceGraph(),
        makeNode('get_ticker', { x: -200, y: 0 }, { symbol: 'AAPL' }, 'aapl'),
      ],
      'price',
      'aapl',
    )
    assert.equal(nodes.filter((n) => n.type === 'get_ticker').length, 1)
    assert.equal(nodes.find((n) => n.id === 'price')?.data.params.buffer, 0)
  })

  it('adds a Get ticker when the symbol is new', () => {
    const nodes = assignPriceTicker(
      [
        ...priceGraph(),
        makeNode('get_ticker', { x: -200, y: 0 }, { symbol: 'AAPL' }, 'aapl'),
      ],
      'price',
      'nvda',
    )
    const added = nodes.filter((n) => n.type === 'get_ticker')
    assert.equal(added.length, 2)
    assert.equal(added.some((n) => n.data.params.symbol === 'NVDA'), true)
    assert.equal(nodes.find((n) => n.id === 'price')?.data.params.buffer, 1)
  })

  it('writes the bound symbol into the saved document', () => {
    const nodes = [
      makeNode('start', { x: 0, y: 0 }, {}, START_NODE_ID),
      makeNode('get_ticker', { x: 0, y: 0 }, { symbol: 'aapl' }, 'aapl'),
    ]
    const doc = toDocument('Bound', nodes, [])
    const start = doc.flow.nodes.find((n) => n.id === START_NODE_ID)
    const ticker = doc.flow.nodes.find((n) => n.id === 'aapl')
    assert.equal(start?.data.params.symbol0, 'AAPL')
    assert.equal(ticker?.data.params.buffer, 0)
    assert.equal(ticker?.data.params.symbol, 'AAPL')
  })
})

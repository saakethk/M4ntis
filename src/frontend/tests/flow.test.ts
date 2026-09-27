import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { readFileSync } from 'node:fs'
import { BLOCK_DEFS, BLOCK_TYPES, PALETTE_BLOCKS } from '../src/blocks/catalog.ts'
import { analyze } from '../src/flow/analyze.ts'
import { START_NODE_ID, checkConnection, connect, makeEdge, makeNode } from '../src/flow/graph.ts'
import { parseProgramFile, programFileName, programFileText } from '../src/flow/programFile.ts'
import { fromDocument, toDocument, toIR } from '../src/flow/serialize.ts'
import { TEMPLATES } from '../src/flow/templates.ts'
import { assignPriceTicker, tickerSymbols } from '../src/flow/tickers.ts'

const start = () => makeNode('start', { x: 0, y: 0 }, { startingBalance: 100000, resolution: '5m' }, START_NODE_ID)

describe('program files', () => {
  it('round-trips a strategy through JSON text', () => {
    const template = TEMPLATES.find((t) => t.id === 'mean_reversion')!.build()
    const text = programFileText('Bands on AAPL', template.nodes, template.edges, { x: 10, y: 20, zoom: 0.8 })
    const loaded = parseProgramFile(text)
    assert.equal(loaded.name, 'Bands on AAPL')
    assert.deepEqual(loaded.nodes.map((n) => n.id).sort(), template.nodes.map((n) => n.id).sort())
    assert.equal(loaded.edges.length, template.edges.length)
    assert.equal(JSON.parse(text).flow.viewport.zoom, 0.8)
    assert.equal(loaded.edges.find((e) => e.source === 'bands')?.className, 'edge-data')
  })

  it('names files after the strategy', () => {
    assert.equal(programFileName('  SMA Crossover / v2 '), 'sma-crossover-v2.m4ntis.json')
    assert.equal(programFileName('!!!'), 'strategy.m4ntis.json')
  })

  it('rejects files that are not strategies with a readable message', () => {
    assert.throws(() => parseProgramFile('{nope'), /not valid JSON/)
    assert.throws(() => parseProgramFile('{"schema":"other"}'), /m4ntis\.strategy\/v1/)
    const unknown = { schema: 'm4ntis.strategy/v1', flow: { nodes: [{ id: 'x', type: 'teleport' }], edges: [] } }
    assert.throws(() => parseProgramFile(JSON.stringify(unknown)), /Unknown block type "teleport"/)
  })

  it('upgrades legacy current_price blocks and adds a missing Start', () => {
    const loaded = fromDocument({ schema: 'm4ntis.strategy/v1', flow: { nodes: [{ id: 'p', type: 'current_price', position: { x: 1, y: 2 } }], edges: [] } })
    assert.equal(loaded.nodes[0].id, START_NODE_ID)
    assert.equal(loaded.nodes[1].type, 'get_ticker')
    assert.equal(loaded.nodes[1].data.params.symbol, 'AAPL')
  })
})

describe('templates', () => {
  for (const template of TEMPLATES) {
    it(`${template.name} has no blocking problems`, () => {
      const { nodes, edges } = template.build()
      const errors = analyze(nodes, edges).filter((d) => d.level === 'error')
      assert.deepEqual(errors, [])
      assert.equal(toIR(nodes, edges).blockedBlocks.length, 0)
    })
  }
})

describe('Z-Score block', () => {
  it('is in the palette and reads N ticks of history', () => {
    assert.ok(PALETTE_BLOCKS.some((b) => b.type === 'z_score'))
    const nodes = [start(), makeNode('z_score', { x: 0, y: 0 }, { n: 25 }, 'z')]
    const edges = [makeEdge('z', 'data:out', 'nowhere', 'data:a')]
    const messages = analyze(nodes, edges).map((d) => d.message)
    assert.ok(messages.some((m) => m.includes('Needs 25 ticks of history')))
    assert.ok(messages.some((m) => m.includes('BUF0 has no stock')))
  })

  it('keeps blocked blocks out of the palette', () => {
    assert.ok(!PALETTE_BLOCKS.some((b) => b.type === 'log' || b.type === 'start'))
  })
})

describe('connections', () => {
  it('rejects mixed kinds and cycles, and replaces the wire on a data input', () => {
    const edges = [makeEdge('a', 'exec:out', 'b', 'exec:in')]
    assert.match(checkConnection({ source: 'b', sourceHandle: 'exec:out', target: 'a', targetHandle: 'exec:in' }, edges) ?? '', /compiler/)
    assert.match(checkConnection({ source: 'a', sourceHandle: 'data:out', target: 'b', targetHandle: 'exec:in' }, edges) ?? '', /Exec ports/)
    const first = connect({ source: 'c1', sourceHandle: 'data:out', target: 'if', targetHandle: 'data:a' }, [])
    const second = connect({ source: 'c2', sourceHandle: 'data:out', target: 'if', targetHandle: 'data:a' }, first)
    assert.deepEqual(second.map((e) => e.source), ['c2'])
  })
})

describe('ticker slots', () => {
  const priceGraph = () => [start(), makeNode('price_n_ticks_ago', { x: 200, y: 80 }, { buffer: 0, n: 10 }, 'price')]

  it('stores the symbol on Start when there is no Get ticker block', () => {
    const nodes = assignPriceTicker(priceGraph(), 'price', 'msft')
    assert.equal(nodes.find((n) => n.id === START_NODE_ID)?.data.params.symbol0, 'MSFT')
    assert.equal(tickerSymbols(nodes)[0], 'MSFT')
  })

  it('reuses a Get ticker that holds the symbol, and adds one for a new symbol', () => {
    const base = [...priceGraph(), makeNode('get_ticker', { x: -200, y: 0 }, { symbol: 'AAPL' }, 'aapl')]
    assert.equal(assignPriceTicker(base, 'price', 'aapl').filter((n) => n.type === 'get_ticker').length, 1)
    const added = assignPriceTicker(base, 'price', 'nvda')
    assert.equal(added.filter((n) => n.type === 'get_ticker').length, 2)
    assert.equal(added.find((n) => n.id === 'price')?.data.params.buffer, 1)
  })

  it('writes bound symbols into the saved document', () => {
    const doc = toDocument('Bound', [start(), makeNode('get_ticker', { x: 0, y: 0 }, { symbol: 'aapl' }, 'aapl')], [])
    assert.equal(doc.flow.nodes.find((n) => n.id === START_NODE_ID)?.data.params.symbol0, 'AAPL')
    assert.equal(doc.flow.nodes.find((n) => n.id === 'aapl')?.data.params.buffer, 0)
  })
})

describe('catalog', () => {
  it('lists the same block types as the backend catalog the assistant uses', () => {
    const python = readFileSync(new URL('../../backend/mantis/blocks/catalog.py', import.meta.url), 'utf8')
    const backend = [...python.matchAll(/^ {4}"(\w+)": Block\(/gm)].map((m) => m[1]).sort()
    const frontend = BLOCK_TYPES.filter((type) => BLOCK_DEFS[type].status !== 'blocked').sort()
    assert.deepEqual(frontend, backend)
  })
})

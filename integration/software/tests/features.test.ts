import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import type { ModelChoice } from '../src/api/assistant.ts'
import type { StrategySummary } from '../src/api/strategies.ts'
import { MODEL_STORAGE_KEY, choiceId, initialChoice, rememberChoice, type ModelStorage } from '../src/features/assistant/modelChoice.ts'
import { filterStrategies, portfolioView } from '../src/features/portfolio/portfolio.ts'
import { applyAssistantGraph, readAssistantGraph, type AssistantGraph } from '../src/flow/assistantGraph.ts'
import { makeNode } from '../src/flow/graph.ts'
import { displayName, relativeTime } from '../src/lib/format.ts'

const MODELS: ModelChoice[] = [
  { provider: 'gemini', model: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash', available: false },
  { provider: 'meta', model: 'muse-spark-1.3', label: 'Muse Spark 1.3', available: true },
  { provider: 'meta', model: 'muse-spark-1.2', label: 'Muse Spark 1.2', available: true },
]

function memory(initial: Record<string, string> = {}): ModelStorage & { saved: Map<string, string> } {
  const saved = new Map(Object.entries(initial))
  return { saved, getItem: (key) => saved.get(key) ?? null, setItem: (key, value) => void saved.set(key, value) }
}

describe('assistant model choice', () => {
  it('prefers a stored usable choice, then the server default, then the first usable model', () => {
    assert.equal(initialChoice(MODELS, null, memory({ [MODEL_STORAGE_KEY]: 'meta:muse-spark-1.2' }))?.model, 'muse-spark-1.2')
    assert.equal(initialChoice(MODELS, { provider: 'meta', model: 'muse-spark-1.2' }, memory())?.model, 'muse-spark-1.2')
    assert.equal(initialChoice(MODELS, { provider: 'gemini', model: 'gemini-3.8-flash' }, memory())?.model, 'muse-spark-1.3')
    assert.equal(initialChoice(MODELS, null, memory({ [MODEL_STORAGE_KEY]: 'gemini:gemini-2.0-flash' }))?.model, 'muse-spark-1.3')
    assert.equal(initialChoice([], null, memory()), null)
  })

  it('remembers the choice and tolerates storage that throws', () => {
    const storage = memory()
    rememberChoice(MODELS[1], storage)
    assert.equal(storage.saved.get(MODEL_STORAGE_KEY), choiceId(MODELS[1]))
    const blocked: ModelStorage = {
      getItem: () => {
        throw new Error('denied')
      },
      setItem: () => {
        throw new Error('denied')
      },
    }
    assert.doesNotThrow(() => rememberChoice(MODELS[1], blocked))
    assert.equal(initialChoice(MODELS, null, blocked)?.model, 'muse-spark-1.3')
  })
})

describe('assistant graphs', () => {
  const graph: AssistantGraph = {
    nodes: [
      { id: 'start', type: 'start', params: { resolution: '15m' } },
      { id: 't0', type: 'get_ticker', params: { symbol: 'NVDA' } },
      { id: 'low', type: 'if', params: { operator: '<=' } },
      { id: 'buy', type: 'buy', params: { quantity: 5 } },
    ],
    edges: [
      { source: 'start', sourceHandle: 'exec:out', target: 'low', targetHandle: 'exec:in' },
      { source: 't0', sourceHandle: 'data:out', target: 'low', targetHandle: 'data:a' },
      { source: 'low', sourceHandle: 'exec:then', target: 'buy', targetHandle: 'exec:in' },
    ],
  }

  it('places and wires every block, keeping existing positions', () => {
    const placed = applyAssistantGraph(graph, [makeNode('get_ticker', { x: 40, y: 80 }, {}, 't0')])
    assert.equal(placed.edges.length, 3)
    assert.deepEqual(placed.nodes.find((n) => n.id === 't0')?.position, { x: 40, y: 80 })
    assert.equal(placed.nodes.find((n) => n.id === 'buy')?.data.params.quantity, 5)
  })

  it('validates server graphs', () => {
    assert.equal(readAssistantGraph(null), null)
    assert.equal(readAssistantGraph(graph)?.nodes.length, 4)
    assert.throws(() => readAssistantGraph({ nodes: [{ id: 1 }], edges: [] }))
    assert.throws(() => applyAssistantGraph({ nodes: [{ id: 'b', type: 'buy', params: {} }], edges: [] }), /Start/)
  })
})

describe('portfolio', () => {
  const rows: StrategySummary[] = [
    { id: 1, name: 'Opening Drive', visibility: 'private', updatedAt: '', lastBacktest: null },
    { id: 2, name: 'Close Auction', visibility: 'public', updatedAt: '', lastBacktest: null },
  ]

  it('chooses the view and filters by name and visibility', () => {
    assert.equal(portfolioView({ loading: true, failed: false, count: 0 }), 'loading')
    assert.equal(portfolioView({ loading: false, failed: true, count: 0 }), 'error')
    assert.equal(portfolioView({ loading: false, failed: false, count: 0 }), 'get-started')
    assert.equal(portfolioView({ loading: false, failed: false, count: 2 }), 'list')
    assert.deepEqual(filterStrategies(rows, 'drive', 'all').map((r) => r.id), [1])
    assert.deepEqual(filterStrategies(rows, '', 'public').map((r) => r.id), [2])
  })
})

describe('format', () => {
  it('formats names and relative times', () => {
    assert.equal(displayName('ada.lovelace@example.com'), 'Ada Lovelace')
    const now = Date.parse('2026-09-27T12:00:00Z')
    assert.equal(relativeTime('2026-09-27T11:59:30Z', now), 'now')
    assert.equal(relativeTime('2026-09-27T09:00:00Z', now), '3h')
  })
})
